//! `start-tonic-server`: run the real Tonic constraint-evaluation
//! server on a Unix socket.
//!
//! Usage: `start-tonic-server [SOCKET_PATH]`
//! Default socket: `/tmp/start-spine-tonic-<pid>.sock`.
//!
//! Local only: Unix socket, no TLS, no auth. Anyone who can reach
//! the socket file can call Evaluate, so run it in a private
//! directory and do not expose the socket. The server evaluates
//! constraints; it does not verify plans and never bypasses the
//! verify step or human approval.

use std::path::PathBuf;

use start_core_spine::server::{default_socket_path, serve_unix};

#[tokio::main]
async fn main() {
    let socket: PathBuf = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(default_socket_path);
    println!("start-tonic-server: listening on unix://{}", socket.display());
    if let Err(e) = serve_unix(&socket).await {
        eprintln!("start-tonic-server: serve error: {e}");
        std::process::exit(1);
    }
}
