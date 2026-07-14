fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut config = prost_build::Config::new();
    config.compile_protos(&["proto/wire.proto"], &["proto/"])?;
    Ok(())
}
