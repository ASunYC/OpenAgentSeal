fn main() {
    let target = std::env::var("TARGET").expect("Cargo did not provide TARGET");
    println!("cargo:rustc-env=OPEN_AGENT_TARGET_TRIPLE={target}");
    tauri_build::build();
}
