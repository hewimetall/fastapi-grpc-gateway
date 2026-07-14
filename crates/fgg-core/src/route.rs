use std::collections::HashMap;

use thiserror::Error;

use crate::bindings::RouteBinding;
use crate::path::{fill_path, urlencoding_encode};
use crate::wire::RpcRequest;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HttpTarget {
    pub method: String,
    pub path: String,
    pub query: String,
    pub body: Vec<u8>,
    pub has_body: bool,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum RouteError {
    #[error("unknown rpc {0}")]
    UnknownRpc(String),
}

fn serde_urlencoded(map: &HashMap<String, String>) -> String {
    map.iter()
        .map(|(k, v)| format!("{}={}", urlencoding_encode(k), urlencoding_encode(v)))
        .collect::<Vec<_>>()
        .join("&")
}

/// Map an RPC name + wire request to an HTTP target (no network I/O).
pub fn build_http_target(
    routes: &HashMap<String, RouteBinding>,
    rpc: &str,
    req: &RpcRequest,
) -> Result<HttpTarget, RouteError> {
    let binding = routes
        .get(rpc)
        .ok_or_else(|| RouteError::UnknownRpc(rpc.to_string()))?
        .clone();

    let path = fill_path(&binding.path, &req.path);
    let query = if req.query.is_empty() {
        String::new()
    } else {
        serde_urlencoded(&req.query)
    };
    let body = if binding.has_body {
        req.body.clone()
    } else {
        Vec::new()
    };

    Ok(HttpTarget {
        method: binding.http_method,
        path,
        query,
        body,
        has_body: binding.has_body,
    })
}

/// Parse `/package.Service/Rpc` style gRPC path into rpc method name.
pub fn rpc_from_grpc_path(full_path: &str, package: &str, service: &str) -> Option<String> {
    let prefix = format!("/{package}.{service}/");
    full_path.strip_prefix(&prefix).map(|s| s.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bindings::RouteBinding;

    fn routes() -> HashMap<String, RouteBinding> {
        let mut m = HashMap::new();
        m.insert(
            "GetUser".into(),
            RouteBinding {
                rpc: "GetUser".into(),
                http_method: "GET".into(),
                path: "/api/users/{user_id}".into(),
                path_params: vec!["user_id".into()],
                query_params: vec![],
                has_body: false,
            },
        );
        m.insert(
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
        m
    }

    #[test]
    fn build_get_with_path_and_query() {
        let req = RpcRequest {
            path: HashMap::from([("user_id".into(), "7".into())]),
            query: HashMap::from([("verbose".into(), "1".into())]),
            body: b"ignored".to_vec(),
        };
        let t = build_http_target(&routes(), "GetUser", &req).unwrap();
        assert_eq!(t.method, "GET");
        assert_eq!(t.path, "/api/users/7");
        assert_eq!(t.query, "verbose=1");
        assert!(t.body.is_empty());
        assert!(!t.has_body);
    }

    #[test]
    fn build_post_keeps_body() {
        let req = RpcRequest {
            path: HashMap::new(),
            query: HashMap::new(),
            body: br#"{"name":"x"}"#.to_vec(),
        };
        let t = build_http_target(&routes(), "PostCreateItem", &req).unwrap();
        assert_eq!(t.method, "POST");
        assert_eq!(t.path, "/api/items");
        assert!(t.query.is_empty());
        assert_eq!(t.body, br#"{"name":"x"}"#);
        assert!(t.has_body);
    }

    #[test]
    fn unknown_rpc() {
        let req = RpcRequest::default();
        let err = build_http_target(&routes(), "Nope", &req).unwrap_err();
        assert_eq!(err, RouteError::UnknownRpc("Nope".into()));
    }

    #[test]
    fn parse_grpc_path() {
        assert_eq!(
            rpc_from_grpc_path("/fastapi_grpc.API/GetHello", "fastapi_grpc", "API").as_deref(),
            Some("GetHello")
        );
        assert!(rpc_from_grpc_path("/other/GetHello", "fastapi_grpc", "API").is_none());
    }

    #[test]
    fn query_encodes_keys_and_values() {
        let req = RpcRequest {
            path: HashMap::new(),
            query: HashMap::from([("a b".into(), "c/d".into())]),
            body: vec![],
        };
        // reuse GetUser but empty path params leaves {user_id}
        let mut rs = routes();
        rs.insert(
            "Search".into(),
            RouteBinding {
                rpc: "Search".into(),
                http_method: "GET".into(),
                path: "/search".into(),
                path_params: vec![],
                query_params: vec!["a b".into()],
                has_body: false,
            },
        );
        let t = build_http_target(&rs, "Search", &req).unwrap();
        assert_eq!(t.query, "a%20b=c%2Fd");
    }
}
