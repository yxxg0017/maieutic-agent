// Windows 发布时不弹出终端窗口
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    maieutic_desktop_lib::run()
}
