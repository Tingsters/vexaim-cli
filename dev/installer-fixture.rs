// Failure-test binary only. Never package this as the real vexaim tool.
fn main() {
    let version = std::env::var("VEXAIM_FIXTURE_VERSION").unwrap_or_else(|_| "0.1.0".into());
    println!("vexaim {version}");
    if std::env::var_os("VEXAIM_FIXTURE_FAIL").is_some() {
        std::process::exit(2);
    }
}
