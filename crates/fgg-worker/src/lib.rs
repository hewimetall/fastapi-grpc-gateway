//! Library surface for fgg-worker (unit-tested; counted by llvm-cov).

use std::collections::HashMap;
use std::convert::Infallible;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context as TaskContext, Poll};

use anyhow::{anyhow, Context, Result};
use bytes::Bytes;
use fgg_core::{
    build_http_target, decode_grpc_payload, encode_grpc_payload, JsonResponse, RpcRequest,
    RouteBinding,
};
use http_body_util::{BodyExt, Full};
use hyper::body::{Body, Frame, Incoming};
use hyper::{Method, Request, Response, StatusCode, Uri};
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use prost::Message;
use tracing::error;

#[derive(Clone)]
pub struct AppState {
    pub upstream: String,
    pub package: String,
    pub service: String,
    pub routes: HashMap<String, RouteBinding>,
    pub client: Client<HttpConnector, Full<Bytes>>,
}

pub struct GrpcUnaryBody {
    pub data: Option<Bytes>,
    pub trailers: Option<http::HeaderMap>,
}

impl Body for GrpcUnaryBody {
    type Data = Bytes;
    type Error = Infallible;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        _cx: &mut TaskContext<'_>,
    ) -> Poll<Option<Result<Frame<Self::Data>, Self::Error>>> {
        if let Some(data) = self.data.take() {
            return Poll::Ready(Some(Ok(Frame::data(data))));
        }
        if let Some(trailers) = self.trailers.take() {
            return Poll::Ready(Some(Ok(Frame::trailers(trailers))));
        }
        Poll::Ready(None)
    }
}

pub fn normalize_upstream(upstream: &str) -> String {
    upstream.trim_end_matches('/').to_string()
}

pub fn rpc_from_grpc_http_path(path: &str, package: &str, service: &str) -> Result<String> {
    let prefix = format!("/{package}.{service}");
    path.strip_prefix(&prefix)
        .and_then(|s| s.strip_prefix('/'))
        .map(|s| s.to_string())
        .ok_or_else(|| anyhow!("unknown path {path}, expected {prefix}/Rpc"))
}

pub fn build_upstream_uri(upstream: &str, path: &str, query: &str) -> Result<Uri> {
    let mut uri_str = format!("{upstream}{path}");
    if !query.is_empty() {
        uri_str.push('?');
        uri_str.push_str(query);
    }
    uri_str.parse().context("parse upstream uri")
}

pub fn grpc_message(msg: JsonResponse) -> Result<Response<GrpcUnaryBody>> {
    let data = encode_grpc_payload(&msg).map_err(|e| anyhow!(e))?;
    let mut trailers = http::HeaderMap::new();
    trailers.insert("grpc-status", http::HeaderValue::from_static("0"));
    Response::builder()
        .status(StatusCode::OK)
        .header("content-type", "application/grpc")
        .body(GrpcUnaryBody {
            data: Some(data),
            trailers: Some(trailers),
        })
        .map_err(|e| anyhow!(e))
}

pub fn grpc_status_only(code: u32, message: &str) -> Response<GrpcUnaryBody> {
    let mut trailers = http::HeaderMap::new();
    trailers.insert(
        "grpc-status",
        http::HeaderValue::from_str(&code.to_string()).unwrap(),
    );
    let msg = message.replace(['\n', '\r'], " ");
    if let Ok(v) = http::HeaderValue::from_str(&msg) {
        trailers.insert("grpc-message", v);
    }
    Response::builder()
        .status(StatusCode::OK)
        .header("content-type", "application/grpc")
        .body(GrpcUnaryBody {
            data: None,
            trailers: Some(trailers),
        })
        .unwrap()
}

pub async fn handle_request(
    state: Arc<AppState>,
    req: Request<Incoming>,
) -> Response<GrpcUnaryBody> {
    match process(state, req).await {
        Ok(resp) => resp,
        Err(err) => {
            error!(error = %err, "rpc failed");
            grpc_status_only(2, &err.to_string())
        }
    }
}

pub async fn process<B>(state: Arc<AppState>, req: Request<B>) -> Result<Response<GrpcUnaryBody>>
where
    B: Body,
    B::Error: Into<Box<dyn std::error::Error + Send + Sync>>,
{
    if req.method() != Method::POST {
        return Ok(grpc_status_only(12, "unimplemented"));
    }
    let path = req.uri().path().to_string();
    let rpc = rpc_from_grpc_http_path(&path, &state.package, &state.service)?;

    let collected = req
        .collect()
        .await
        .map_err(|e| anyhow!(e.into()))?
        .to_bytes();
    let proto_bytes = decode_grpc_payload(&collected).map_err(|e| anyhow!(e))?;
    let rpc_req = RpcRequest::decode(proto_bytes).context("decode RpcRequest")?;

    let target = build_http_target(&state.routes, &rpc, &rpc_req).map_err(|e| anyhow!(e))?;
    let uri = build_upstream_uri(&state.upstream, &target.path, &target.query)?;
    let method = Method::from_bytes(target.method.as_bytes()).unwrap_or(Method::GET);
    let body_bytes = Bytes::from(target.body);

    let mut builder = Request::builder().method(method).uri(uri);
    if target.has_body && !body_bytes.is_empty() {
        builder = builder.header(hyper::header::CONTENT_TYPE, "application/json");
        builder = builder.header(hyper::header::CONTENT_LENGTH, body_bytes.len());
    }
    let upstream_req = builder
        .body(Full::new(body_bytes))
        .context("build upstream req")?;

    let upstream = state
        .client
        .request(upstream_req)
        .await
        .context("upstream request")?;
    let status = upstream.status().as_u16() as i32;
    let mut headers = HashMap::new();
    for (k, v) in upstream.headers().iter() {
        if let Ok(val) = v.to_str() {
            headers.insert(k.as_str().to_string(), val.to_string());
        }
    }
    let body = upstream.collect().await?.to_bytes().to_vec();

    grpc_message(JsonResponse {
        status_code: status,
        body,
        headers,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use fgg_core::encode_grpc_payload;
    use futures_util::future::poll_fn;
    use http_body_util::Full;
    use hyper::server::conn::http1;
    use hyper::service::service_fn;
    use hyper_util::rt::{TokioExecutor, TokioIo};
    use tokio::net::TcpListener;

    fn state_with_routes(
        upstream: String,
        routes: HashMap<String, RouteBinding>,
    ) -> Arc<AppState> {
        let client = Client::builder(TokioExecutor::new()).build_http();
        Arc::new(AppState {
            upstream,
            package: "fastapi_grpc".into(),
            service: "API".into(),
            routes,
            client,
        })
    }

    #[test]
    fn normalize_upstream_trims_slash() {
        assert_eq!(normalize_upstream("http://x/"), "http://x");
        assert_eq!(normalize_upstream("http://x"), "http://x");
    }

    #[test]
    fn rpc_path_ok_and_err() {
        assert_eq!(
            rpc_from_grpc_http_path("/fastapi_grpc.API/GetHello", "fastapi_grpc", "API").unwrap(),
            "GetHello"
        );
        assert!(rpc_from_grpc_http_path("/nope", "fastapi_grpc", "API").is_err());
    }

    #[test]
    fn upstream_uri_with_and_without_query() {
        let u = build_upstream_uri("http://127.0.0.1:8000", "/api/hello", "").unwrap();
        assert_eq!(u.to_string(), "http://127.0.0.1:8000/api/hello");
        let u = build_upstream_uri("http://127.0.0.1:8000", "/s", "q=1").unwrap();
        assert_eq!(u.to_string(), "http://127.0.0.1:8000/s?q=1");
    }

    #[test]
    fn grpc_status_and_message() {
        let resp = grpc_status_only(12, "bad\nmsg");
        assert_eq!(resp.status(), StatusCode::OK);
        let msg = JsonResponse {
            status_code: 200,
            body: b"{}".to_vec(),
            headers: HashMap::new(),
        };
        assert!(grpc_message(msg).is_ok());
    }

    #[tokio::test]
    async fn grpc_body_polls_data_then_trailers_then_none() {
        let mut body = GrpcUnaryBody {
            data: Some(Bytes::from_static(b"abc")),
            trailers: {
                let mut t = http::HeaderMap::new();
                t.insert("grpc-status", http::HeaderValue::from_static("0"));
                Some(t)
            },
        };
        let f1 = poll_fn(|cx| Pin::new(&mut body).poll_frame(cx)).await;
        assert!(f1.unwrap().unwrap().is_data());
        let f2 = poll_fn(|cx| Pin::new(&mut body).poll_frame(cx)).await;
        assert!(f2.unwrap().unwrap().is_trailers());
        let f3 = poll_fn(|cx| Pin::new(&mut body).poll_frame(cx)).await;
        assert!(f3.is_none());
    }

    #[tokio::test]
    async fn process_rejects_non_post() {
        let state = state_with_routes("http://127.0.0.1:9".into(), HashMap::new());
        let resp = process(
            state,
            Request::builder()
                .method(Method::GET)
                .uri("/fastapi_grpc.API/X")
                .body(Full::new(Bytes::new()))
                .unwrap(),
        )
        .await
        .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn process_get_against_mock_upstream() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let io = TokioIo::new(stream);
            http1::Builder::new()
                .serve_connection(
                    io,
                    service_fn(|_req| async move {
                        Ok::<_, Infallible>(
                            Response::builder()
                                .status(200)
                                .header("x-test", "1")
                                .body(Full::new(Bytes::from_static(br#"{"ok":true}"#)))
                                .unwrap(),
                        )
                    }),
                )
                .await
                .ok();
        });

        let mut routes = HashMap::new();
        routes.insert(
            "GetHello".into(),
            RouteBinding {
                rpc: "GetHello".into(),
                http_method: "GET".into(),
                path: "/api/hello".into(),
                path_params: vec![],
                query_params: vec![],
                has_body: false,
            },
        );
        let state = state_with_routes(format!("http://{addr}"), routes);
        let framed = encode_grpc_payload(&RpcRequest::default()).unwrap();
        let resp = process(
            state,
            Request::builder()
                .method(Method::POST)
                .uri("/fastapi_grpc.API/GetHello")
                .body(Full::new(framed))
                .unwrap(),
        )
        .await
        .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn process_post_with_json_body() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let io = TokioIo::new(stream);
            http1::Builder::new()
                .serve_connection(
                    io,
                    service_fn(|req| async move {
                        let bytes = req.collect().await.unwrap().to_bytes();
                        assert_eq!(bytes.as_ref(), br#"{"name":"x"}"#);
                        Ok::<_, Infallible>(
                            Response::builder()
                                .status(201)
                                .body(Full::new(Bytes::from_static(br#"{"id":1}"#)))
                                .unwrap(),
                        )
                    }),
                )
                .await
                .ok();
        });

        let mut routes = HashMap::new();
        routes.insert(
            "PostCreateItem".into(),
            RouteBinding {
                rpc: "PostCreateItem".into(),
                http_method: "POST".into(),
                path: "/api/items".into(),
                path_params: vec![],
                query_params: vec![],
                has_body: true,
            },
        );
        let state = state_with_routes(format!("http://{addr}"), routes);
        let rpc_req = RpcRequest {
            path: HashMap::new(),
            query: HashMap::new(),
            body: br#"{"name":"x"}"#.to_vec(),
        };
        let framed = encode_grpc_payload(&rpc_req).unwrap();
        let resp = process(
            state,
            Request::builder()
                .method(Method::POST)
                .uri("/fastapi_grpc.API/PostCreateItem")
                .body(Full::new(framed))
                .unwrap(),
        )
        .await
        .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn process_unknown_rpc_errors() {
        let state = state_with_routes("http://127.0.0.1:9".into(), HashMap::new());
        let framed = encode_grpc_payload(&RpcRequest::default()).unwrap();
        let err = process(
            state,
            Request::builder()
                .method(Method::POST)
                .uri("/fastapi_grpc.API/Nope")
                .body(Full::new(framed))
                .unwrap(),
        )
        .await;
        assert!(err.is_err());
    }
}
