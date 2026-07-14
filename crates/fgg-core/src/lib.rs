//! Protocol core shared by fastapi-grpc-gateway tooling.
//!
//! Pure Rust helpers: bindings.toml, gRPC length-prefixed frames, path templates,
//! and prost wire messages (`RpcRequest` / `JsonResponse`).

pub mod bindings;
pub mod grpc_frame;
pub mod path;
pub mod route;

pub mod wire {
    include!(concat!(env!("OUT_DIR"), "/fgg.wire.rs"));
}

pub use bindings::{load_bindings, BindingsFile, RouteBinding};
pub use grpc_frame::{decode_grpc_payload, encode_grpc_payload, GrpcFrameError};
pub use path::{fill_path, urlencoding_encode};
pub use route::{build_http_target, HttpTarget};
pub use wire::{JsonResponse, RpcRequest};
