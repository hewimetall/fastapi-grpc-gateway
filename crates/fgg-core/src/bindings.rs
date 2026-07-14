use std::collections::HashMap;
use std::fs;
use std::path::Path;

use serde::Deserialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum BindingsError {
    #[error("read bindings: {0}")]
    Io(#[from] std::io::Error),
    #[error("parse bindings.toml: {0}")]
    Parse(#[from] toml::de::Error),
}

#[derive(Debug, Deserialize, Clone, PartialEq, Eq)]
pub struct BindingsFile {
    pub package: String,
    pub service: String,
    #[serde(default)]
    pub route: Vec<RouteBinding>,
}

#[derive(Debug, Deserialize, Clone, PartialEq, Eq)]
pub struct RouteBinding {
    pub rpc: String,
    pub http_method: String,
    pub path: String,
    #[serde(default)]
    pub path_params: Vec<String>,
    #[serde(default)]
    pub query_params: Vec<String>,
    #[serde(default)]
    pub has_body: bool,
}

impl BindingsFile {
    pub fn parse(text: &str) -> Result<Self, BindingsError> {
        Ok(toml::from_str(text)?)
    }

    pub fn routes_by_rpc(&self) -> HashMap<String, RouteBinding> {
        let mut map = HashMap::new();
        for route in &self.route {
            map.insert(route.rpc.clone(), route.clone());
        }
        map
    }

    pub fn full_service_path(&self) -> String {
        format!("{}.{}", self.package, self.service)
    }
}

pub fn load_bindings(path: impl AsRef<Path>) -> Result<BindingsFile, BindingsError> {
    let raw = fs::read_to_string(path)?;
    BindingsFile::parse(&raw)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    const SAMPLE: &str = r#"
package = "fastapi_grpc"
service = "API"

[[route]]
rpc = "GetHello"
http_method = "GET"
path = "/api/hello"
path_params = []
query_params = []
has_body = false

[[route]]
rpc = "GetUser"
http_method = "GET"
path = "/api/users/{user_id}"
path_params = ["user_id"]
query_params = []
has_body = false

[[route]]
rpc = "PostCreateItem"
http_method = "POST"
path = "/api/items"
path_params = []
query_params = []
has_body = true
"#;

    #[test]
    fn parse_sample_bindings() {
        let file = BindingsFile::parse(SAMPLE).unwrap();
        assert_eq!(file.package, "fastapi_grpc");
        assert_eq!(file.service, "API");
        assert_eq!(file.route.len(), 3);
        assert_eq!(file.full_service_path(), "fastapi_grpc.API");
        let map = file.routes_by_rpc();
        assert!(map["GetHello"].has_body == false);
        assert!(map["PostCreateItem"].has_body);
        assert_eq!(map["GetUser"].path_params, vec!["user_id".to_string()]);
    }

    #[test]
    fn parse_empty_routes_default() {
        let file = BindingsFile::parse(
            r#"
package = "p"
service = "S"
"#,
        )
        .unwrap();
        assert!(file.route.is_empty());
        assert!(file.routes_by_rpc().is_empty());
    }

    #[test]
    fn parse_invalid_toml() {
        let err = BindingsFile::parse("not = [toml").unwrap_err();
        assert!(matches!(err, BindingsError::Parse(_)));
    }

    #[test]
    fn load_from_temp_file() {
        let dir = std::env::temp_dir();
        let path = dir.join(format!("fgg-bindings-{}.toml", std::process::id()));
        {
            let mut f = fs::File::create(&path).unwrap();
            f.write_all(SAMPLE.as_bytes()).unwrap();
        }
        let file = load_bindings(&path).unwrap();
        assert_eq!(file.route.len(), 3);
        let _ = fs::remove_file(&path);
    }

    #[test]
    fn load_missing_file() {
        let err = load_bindings("/tmp/does-not-exist-fgg-bindings.toml").unwrap_err();
        assert!(matches!(err, BindingsError::Io(_)));
    }
}
