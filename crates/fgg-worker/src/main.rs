//! fgg-worker binary — gRPC lives here (Rust), not in Python.
//!
//! Flow: gRPC client → this process → HTTP → ASGI server → FastAPI

use std::convert::Infallible;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{Context, Result};
use clap::Parser;
use fgg_core::load_bindings;
use fgg_worker::{handle_request, normalize_upstream, AppState};
use hyper::body::Incoming;
use hyper::server::conn::http2;
use hyper::service::service_fn;
use hyper::{Request, Response};
use hyper_util::client::legacy::Client;
use hyper_util::rt::{TokioExecutor, TokioIo};
use tokio::net::TcpListener;
use tracing::{info, warn};

#[derive(Debug, Parser)]
#[command(
    name = "fgg-worker",
    about = "Rust gRPC worker: unary RPCs → HTTP → ASGI upstream (no Python gRPC)"
)]
struct Args {
    #[arg(long, env = "FGG_BIND", default_value = "0.0.0.0:50051")]
    bind: SocketAddr,

    #[arg(long, env = "FGG_UPSTREAM", default_value = "http://127.0.0.1:8000")]
    upstream: String,

    #[arg(long, env = "FGG_BINDINGS")]
    bindings: PathBuf,
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
    let file = load_bindings(&args.bindings)
        .with_context(|| format!("load bindings {}", args.bindings.display()))?;
    let routes = file.routes_by_rpc();
    info!(
        package = %file.package,
        service = %file.service,
        routes = routes.len(),
        upstream = %args.upstream,
        "loaded bindings"
    );

    let client = Client::builder(TokioExecutor::new()).build_http();
    let state = Arc::new(AppState {
        upstream: normalize_upstream(&args.upstream),
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
            let svc = service_fn(move |req: Request<Incoming>| {
                let state = state.clone();
                async move {
                    Ok::<Response<_>, Infallible>(handle_request(state, req).await)
                }
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
