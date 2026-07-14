use std::collections::HashMap;
use std::convert::Infallible;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context as TaskContext, Poll};

use anyhow::{anyhow, Context, Result};
use bytes::{Buf, BufMut, Bytes, BytesMut};
use clap::Parser;
use http_body_util::{BodyExt, Full};
use hyper::body::{Body, Frame, Incoming};
use hyper::server::conn::http2;
use hyper::service::service_fn;
use hyper::{Method, Request, Response, StatusCode, Uri};
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use hyper_util::rt::{TokioExecutor, TokioIo};
use prost::Message;
use serde::Deserialize;
use tokio::net::TcpListener;
use tracing::{error, info, warn};

pub mod wire {
    include!(concat!(env!("OUT_DIR"), "/fgg.wire.rs"));
}

use wire::{JsonResponse, RpcRequest};

#[derive(Debug, Parser)]
#[command(name = "fgg-worker", about = "gRPC→HTTP worker for FastAPI behind Granian")]
struct Args {
    #[arg(long, env = "FGG_BIND", default_value = "0.0.0.0:50051")]
    bind: SocketAddr,

    #[arg(long, env = "FGG_UPSTREAM", default_value = "http://127.0.0.1:8000")]
    upstream: String,

    #[arg(long, env = "FGG_BINDINGS")]
    bindings: PathBuf,
}

#[derive(Debug, Deserialize, Clone)]
struct BindingsFile {
    package: String,
    service: String,
    #[serde(default)]
    route: Vec<RouteBinding>,
}

#[allow(dead_code)]
#[derive(Debug, Deserialize, Clone)]
struct RouteBinding {
    rpc: String,
    http_method: String,
    path: String,
    #[serde(default)]
    path_params: Vec<String>,
    #[serde(default)]
    query_params: Vec<String>,
    #[serde(default)]
    has_body: bool,
}

#[derive(Clone)]
struct AppState {
    upstream: String,
    package: String,
    service: String,
    routes: HashMap<String, RouteBinding>,
    client: Client<HttpConnector, Full<Bytes>>,
}

struct GrpcUnaryBody {
    data: Option<Bytes>,
    trailers: Option<http::HeaderMap>,
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

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "fgg_worker=info,info".into()),
        )
        .init();

    let args = Args::parse();
    let raw = std::fs::read_to_string(&args.bindings)
        .with_context(|| format!("read bindings {}", args.bindings.display()))?;
    let file: BindingsFile = toml::from_str(&raw).context("parse bindings.toml")?;
    let mut routes = HashMap::new();
    for r in file.route {
        routes.insert(r.rpc.clone(), r);
    }
    info!(
        package = %file.package,
        service = %file.service,
        routes = routes.len(),
        upstream = %args.upstream,
        "loaded bindings"
    );

    let client = Client::builder(TokioExecutor::new()).build_http();
    let state = Arc::new(AppState {
        upstream: args.upstream.trim_end_matches('/').to_string(),
        package: file.package,
        service: file.service,
        routes,
        client,
    });

    let listener = TcpListener::bind(args.bind).await?;
    info!(%args.bind, "fgg-worker listening (HTTP/2 gRPC)");

    loop {
        let (stream, peer) = listener.accept().await?;
        let state = state.clone();
        tokio::spawn(async move {
            let io = TokioIo::new(stream);
            let svc = service_fn(move |req| {
                let state = state.clone();
                async move { Ok::<_, Infallible>(handle_request(state, req).await) }
            });
            if let Err(err) = http2::Builder::new(TokioExecutor::new())
                .serve_connection(io, svc)
                .await
            {
                warn!(%peer, error = %err, "connection error");
            }
        });
    }
}

async fn handle_request(
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

async fn process(
    state: Arc<AppState>,
    req: Request<Incoming>,
) -> Result<Response<GrpcUnaryBody>> {
    if req.method() != Method::POST {
        return Ok(grpc_status_only(12, "unimplemented"));
    }
    let path = req.uri().path().to_string();
    let prefix = format!("/{}.{}", state.package, state.service);
    let rpc = path
        .strip_prefix(&prefix)
        .and_then(|s| s.strip_prefix('/'))
        .ok_or_else(|| anyhow!("unknown path {path}, expected {prefix}/Rpc"))?
        .to_string();

    let binding = state
        .routes
        .get(&rpc)
        .ok_or_else(|| anyhow!("rpc {rpc} not in bindings"))?
        .clone();

    let collected = req.collect().await?.to_bytes();
    let proto_bytes = decode_grpc_payload(&collected)?;
    let rpc_req = RpcRequest::decode(proto_bytes).context("decode RpcRequest")?;

    let http_path = fill_path(&binding.path, &rpc_req.path);
    let mut uri_str = format!("{}{}", state.upstream, http_path);
    if !rpc_req.query.is_empty() {
        uri_str.push('?');
        uri_str.push_str(&serde_urlencoded(&rpc_req.query));
    }
    let uri: Uri = uri_str.parse().context("parse upstream uri")?;

    let method = Method::from_bytes(binding.http_method.as_bytes())
        .unwrap_or(Method::GET);

    let body_bytes = if binding.has_body {
        Bytes::from(rpc_req.body.clone())
    } else {
        Bytes::new()
    };

    let mut builder = Request::builder().method(method).uri(uri);
    if binding.has_body && !body_bytes.is_empty() {
        builder = builder.header(hyper::header::CONTENT_TYPE, "application/json");
        builder = builder.header(hyper::header::CONTENT_LENGTH, body_bytes.len());
    }
    let upstream_req = builder.body(Full::new(body_bytes)).context("build upstream req")?;

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

    let msg = JsonResponse {
        status_code: status,
        body,
        headers,
    };
    grpc_message(msg)
}

fn fill_path(template: &str, params: &HashMap<String, String>) -> String {
    let mut path = template.to_string();
    for (k, v) in params {
        path = path.replace(&format!("{{{k}}}"), &urlencoding_encode(v));
    }
    path
}

fn urlencoding_encode(s: &str) -> String {
    let mut out = String::new();
    for b in s.as_bytes() {
        match *b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(*b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

fn serde_urlencoded(map: &HashMap<String, String>) -> String {
    map.iter()
        .map(|(k, v)| format!("{}={}", urlencoding_encode(k), urlencoding_encode(v)))
        .collect::<Vec<_>>()
        .join("&")
}

fn decode_grpc_payload(buf: &Bytes) -> Result<&[u8]> {
    if buf.len() < 5 {
        return Err(anyhow!("grpc frame too short"));
    }
    if buf[0] != 0 {
        return Err(anyhow!("compressed grpc messages not supported"));
    }
    let len = (&buf[1..5]).get_u32() as usize;
    if buf.len() < 5 + len {
        return Err(anyhow!("grpc frame truncated"));
    }
    Ok(&buf[5..5 + len])
}

fn encode_grpc_payload(msg: &impl Message) -> Result<Bytes> {
    let mut body = BytesMut::new();
    body.put_u8(0);
    let mut proto = BytesMut::new();
    msg.encode(&mut proto)?;
    body.put_u32(proto.len() as u32);
    body.extend_from_slice(&proto);
    Ok(body.freeze())
}

fn grpc_message(msg: JsonResponse) -> Result<Response<GrpcUnaryBody>> {
    let data = encode_grpc_payload(&msg)?;
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

fn grpc_status_only(code: u32, message: &str) -> Response<GrpcUnaryBody> {
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
