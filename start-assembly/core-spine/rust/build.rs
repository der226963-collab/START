//! Build script: generate the Tonic server/client code from
//! `../proto/constraint_evaluation.proto` with tonic-prost-build
//! (in tonic 0.14 the codegen lives in `tonic-prost-build`, not in
//! `tonic-build` — `tonic_build::configure()` no longer exists).
//!
//! tonic-prost-build (via prost-build) needs a `protoc` binary. Resolution
//! order, first one found wins:
//!   1. `$PROTOC` if set in the environment;
//!   2. a `protoc` on `PATH`;
//!   3. the `grpc_tools` package bundled with the spine's Python
//!      venv (`../.venv/bin/python -m grpc_tools.protoc`, libprotoc
//!      35.1 — verified 2026-11-11), via a small wrapper script
//!      written into `OUT_DIR` and pointed at with `$PROTOC`.
//! No `protoc` is vendored and no system install is attempted; if
//! none of the three is found the build fails with a plain message
//! saying so.

use std::io::Write;
use std::path::{Path, PathBuf};

fn python_with_grpc_tools() -> Option<PathBuf> {
    // Candidates, in order: the spine venv first (known to have
    // grpcio-tools), then whatever `python3` / `python` resolves to.
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(manifest_dir) = std::env::var("CARGO_MANIFEST_DIR") {
        candidates.push(
            Path::new(&manifest_dir)
                .join("..")
                .join(".venv")
                .join("bin")
                .join("python"),
        );
    }
    candidates.push(PathBuf::from("python3"));
    candidates.push(PathBuf::from("python"));
    for py in candidates {
        let ok = std::process::Command::new(&py)
            .args(["-c", "import grpc_tools"])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false);
        if ok {
            return Some(py);
        }
    }
    None
}

fn main() {
    let out_dir = PathBuf::from(std::env::var("OUT_DIR").unwrap());
    if std::env::var_os("PROTOC").is_none()
        && which_protoc().is_none()
    {
        if let Some(py) = python_with_grpc_tools() {
            let wrapper = out_dir.join("protoc");
            let mut f = std::fs::File::create(&wrapper)
                .expect("write protoc wrapper");
            writeln!(f, "#!/bin/sh").unwrap();
            writeln!(f, "exec \"{}\" -m grpc_tools.protoc \"$@\"",
                     py.display()).unwrap();
            drop(f);
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&wrapper,
                    std::fs::Permissions::from_mode(0o755)).unwrap();
            }
            std::env::set_var("PROTOC", &wrapper);
            println!("cargo:warning=using grpc_tools protoc via {}", py.display());
        } else {
            panic!("no protoc found: set $PROTOC, put protoc on PATH, \
                    or install grpcio-tools in the spine .venv");
        }
    }
    tonic_prost_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(
            &["../proto/constraint_evaluation.proto"],
            &["../proto"],
        )
        .expect("tonic-prost-build failed to compile constraint_evaluation.proto");
    println!("cargo:rerun-if-changed=../proto/constraint_evaluation.proto");
}

fn which_protoc() -> Option<PathBuf> {
    std::env::var_os("PATH").and_then(|paths| {
        std::env::split_paths(&paths).find_map(|dir| {
            let p = dir.join("protoc");
            if p.is_file() { Some(p) } else { None }
        })
    })
}
