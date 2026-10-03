#[tauri::command]
fn print_page(window: tauri::WebviewWindow) -> Result<(), String> {
    window.print().map_err(|e| e.to_string())
}

/// Upload a local PDF file to S3, then delete the temp file.
/// Credentials are passed from JS (read from ~/hoa-system/tauri/s3_config.json).
/// Rust handles the HTTPS request directly — no CORS constraints.
#[tauri::command]
async fn upload_pdf_to_s3(
    local_path: String,
    bucket: String,
    key: String,
    region: String,
    access_key: String,
    secret_key: String,
) -> Result<(), String> {
    use aws_sdk_s3::primitives::ByteStream;
    use aws_sdk_s3::config::{Credentials, Region};
    use aws_sdk_s3::Client;

    // Read the temp PDF written by JS
    let bytes = std::fs::read(&local_path)
        .map_err(|e| format!("Cannot read temp file {}: {}", local_path, e))?;

    // Build S3 client with explicit credentials from the config file
    let creds = Credentials::new(&access_key, &secret_key, None, None, "hoa-tauri");
    let config = aws_sdk_s3::Config::builder()
        .credentials_provider(creds)
        .region(Region::new(region))
        .build();
    let client = Client::from_conf(config);

    // Upload
    client
        .put_object()
        .bucket(&bucket)
        .key(&key)
        .body(ByteStream::from(bytes))
        .content_type("application/pdf")
        .send()
        .await
        .map_err(|e| format!("S3 upload failed: {}", e))?;

    // Clean up temp file (best-effort — don't fail the command if removal fails)
    let _ = std::fs::remove_file(&local_path);

    Ok(())
}

#[tauri::command]
async fn write_error_log(entry: String) -> Result<(), String> {
    use std::io::Write;
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
    let dir = std::path::Path::new(&home).join("hoa-system").join("tauri");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let path = dir.join("errors.log");
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .map_err(|e| e.to_string())?;
    writeln!(file, "{}", entry).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_sql::Builder::default().build())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![print_page, upload_pdf_to_s3, write_error_log])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
