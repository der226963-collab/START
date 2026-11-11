//! egg e-graph rewrite demo (egraphs-good/egg, MIT).
//!
//! Simplify `x + 0` to `x` by equality saturation. Returns the
//! simplified expression as a string, or an error string.

use egg::{rewrite as rw, *};

define_language! {
    pub enum Math {
        "+" = Add([Id; 2]),
        "*" = Mul([Id; 2]),
        Num(i32),
        Var(Symbol),
    }
}

pub fn simplify_add_zero(expr: &str) -> Result<String, String> {
    let expr: RecExpr<Math> = expr.parse().map_err(|e| format!("parse: {e}"))?;
    let rules: &[Rewrite<Math, ()>] = &[
        rw!("add-zero"; "(+ ?a 0)" => "?a"),
        rw!("mul-one"; "(* ?a 1)" => "?a"),
        rw!("mul-zero"; "(* ?a 0)" => "0"),
    ];
    let runner = Runner::default().with_expr(&expr).run(rules);
    let extractor = Extractor::new(&runner.egraph, AstSize);
    let (_cost, best) = extractor.find_best(runner.roots[0]);
    Ok(best.to_string())
}
