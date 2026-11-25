//! `mcp.panel` (seat S5.2): car-control's panel pieces over a world, for `tests/rustdiff/diffs_mcp.py` `PanelDiff`.
//!
//! Request: `{"call": "mcp.panel", "world": {...}, "preference": text|null, "pages": [{"data", "theme", "design",
//! "text", "face", "day"}, ...]}` (a key left out is the reference's default; `"face": null` is a face Windows would
//! not name). Reply value: `{"style", "script", "names", "prefixes", "font_stack", "pages": [text or {"raised": class}],
//! "tile": [...], "rules": [...]}`.

use car_control::host::Host;
use car_control::mcp::panel::{self, Page};
use car_machine::json::{Map, Value};

use crate::bridge::WorldHost;
use crate::object;

fn text(value: Option<&Value>) -> Option<String> {
    match value {
        Some(Value::Str(text)) => text.as_str().map(str::to_owned),
        _ => None,
    }
}

fn strings(items: &[String]) -> Value {
    Value::Array(
        items
            .iter()
            .map(|each| Value::from(each.as_str()))
            .collect(),
    )
}

/// `mcp.panel`.
pub fn panel(request: &Map) -> Value {
    let world = match request.get("world") {
        Some(Value::Object(map)) => map.clone(),
        _ => Map::new(),
    };
    let host = WorldHost::from_world(&world, ".");
    let environ = |name: &str| host.environ(name);
    let windows = || host.windows_languages();
    car_words::l10n::set_preference(
        text(request.get("preference")).as_deref(),
        &environ,
        &windows,
    );
    let style = panel::style().unwrap_or_else(|class| format!("<raised {class}>"));
    let (names, prefixes) = panel::panel_keys();
    let mut pages = Vec::new();
    if let Some(Value::Array(asked)) = request.get("pages") {
        for each in asked {
            let Value::Object(each) = each else { continue };
            let page = Page {
                data: each.get("data").cloned(),
                theme: text(each.get("theme")),
                design: text(each.get("design")),
                text: each.get("text").cloned(),
                face: each.get("face").map(|face| text(Some(face))),
                day: text(each.get("day")),
            };
            pages.push(match panel::settings_page(&host, &page) {
                Ok(made) => Value::from(made),
                Err(class) => object([("raised", Value::from(class))]),
            });
        }
    }
    let mut tiles = Vec::new();
    for theme in ["light", "dark"] {
        for design in ["soft", "classic", "plain"] {
            tiles.push(Value::from(
                panel::tile_elevation(theme, design).unwrap_or_default(),
            ));
        }
    }
    object([
        ("style", Value::from(style.as_str())),
        ("script", Value::from(panel::SCRIPT)),
        ("names", strings(&names)),
        ("prefixes", strings(&prefixes)),
        ("font_stack", Value::from(panel::font_stack(&style))),
        ("pages", Value::Array(pages)),
        ("tile", Value::Array(tiles)),
        (
            "rules",
            Value::Array(vec![
                Value::from(panel::design_rules().unwrap_or_default()),
                Value::from(panel::right_to_left_rules().unwrap_or_default()),
            ]),
        ),
    ])
}
