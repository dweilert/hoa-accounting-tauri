// App configuration — read from ~/hoa-system/tauri/config.json
// Using BaseDirectory.Home so no username is hardcoded anywhere in the app.

const CONFIG_REL_PATH = "hoa-system/tauri/config.json";

export type AppConfig = {
  db_path: string;
  python_path?: string;
  scripts_dir?: string;
};

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function readConfig(): Promise<AppConfig | null> {
  if (!isTauri()) return null;
  const { readTextFile, BaseDirectory } = await import("@tauri-apps/plugin-fs");
  const text = await readTextFile(CONFIG_REL_PATH, { baseDir: BaseDirectory.Home });
  return JSON.parse(text) as AppConfig;
}

export async function writeConfig(config: AppConfig): Promise<void> {
  if (!isTauri()) return;
  const { writeTextFile, mkdir, BaseDirectory } = await import("@tauri-apps/plugin-fs");
  await mkdir("hoa-system/tauri", { baseDir: BaseDirectory.Home, recursive: true });
  await writeTextFile(CONFIG_REL_PATH, JSON.stringify(config, null, 2), {
    baseDir: BaseDirectory.Home,
  });
}
