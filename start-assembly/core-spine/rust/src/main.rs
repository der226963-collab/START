//! start-spine binary: runs the Cedar and egg checks and prints
//! one line per check. Exit code 0 only if every check passes.
//! The real Tonic server lives in the separate `start-tonic-server`
//! binary (see server.rs); this binary does not start a server.

use start_core_spine::{cedar_eval, egg_demo};

fn main() {
    let mut ok = true;
    let checks = [
        ("cedar: planner may plan synthetic",
         cedar_eval::planner_may_plan_synthetic().unwrap_or(false), true),
        ("cedar: planner may not plan real",
         cedar_eval::planner_may_not_plan_real().unwrap_or(true), false),
        ("cedar: publish denied when unverified",
         cedar_eval::publish_denied_unverified().unwrap_or(true), false),
        ("cedar: publish allowed when verified+approved",
         cedar_eval::publish_allowed_verified_and_approved().unwrap_or(false), true),
    ];
    for (name, got, want) in checks {
        let pass = got == want;
        ok &= pass;
        println!("{}: got={} want={} {}", name, got, want, if pass { "PASS" } else { "FAIL" });
    }
    match egg_demo::simplify_add_zero("(+ x 0)") {
        Ok(s) => {
            let pass = s == "x";
            ok &= pass;
            println!("egg: (+ x 0) -> {s} {}", if pass { "PASS" } else { "FAIL" });
        }
        Err(e) => {
            ok = false;
            println!("egg: error {e} FAIL");
        }
    }
    if !ok {
        std::process::exit(1);
    }
}
