//! `mcp/panel.py`: the settings panel Codex renders inside the conversation - one self-contained page, no network.
//!
//! The stylesheet and the script are `assets/panel.css` and `assets/panel.js` of this crate: the bytes of the
//! reference's `mcp/assets/` read with universal newlines, as `panel._asset` reads them, held equal to the shipped
//! files by `tests/rustdiff/diffs_mcp.py` `PanelDiff`. The stylesheet's `@TOKEN@`s are filled from car-brand, as the
//! reference fills them from `brand`. What the page asks of Windows - the text size and the UI font - is the Host's.

use car_brand::data::{D, Num};
use car_brand::{Py, css, days, tables_gen as brand};
use car_machine::json::{Map, Options, Str, Value, to_string};

use crate::host::Host;

const STYLE_TEMPLATE: &str = include_str!("../../assets/panel.css");
/// `_SCRIPT`.
pub const SCRIPT: &str = include_str!("../../assets/panel.js");

/// `textsize.HIGHEST`.
const HIGHEST_TEXT: f64 = 225.0;
/// `TEXT_HOLDERS`.
pub const TEXT_HOLDERS: &[&str] = &[
    "button_height",
    "field_height",
    "chip_height",
    "segment_height",
    "count_height",
    "count_min_width",
    "callout_badge",
];
/// `LINE_CONTROL`.
pub const LINE_CONTROL: f64 = 20.0;
/// `typeface.SEGOE`.
const SEGOE: &str = "Segoe UI";

fn hyphens(name: &str) -> String {
    name.replace('_', "-")
}

/// `css_shadow(shadow)`: one of brand's Shadows as CSS.
pub fn css_shadow(shadow: &car_brand::elevation::Shadow) -> String {
    format!(
        "{}{} {} {} color-mix(in srgb, var(--{}) {}%, transparent)",
        if shadow.inset { "inset " } else { "" },
        css::css_length(shadow.dx.f()),
        css::css_length(shadow.dy.f()),
        css::css_length(shadow.blur.f()),
        hyphens(shadow.token),
        car_brand::pyfmt::round_int(shadow.alpha.f() * 100.0)
    )
}

/// `tile_elevation(theme, design)`: `--elev-tile` for one theme.
pub fn tile_elevation(theme: &str, design: &str) -> Py<String> {
    if !car_brand::design_depth(Some(design))? {
        return Ok("--elev-tile: none;".to_owned());
    }
    let mut parts = vec!["var(--elev-control)".to_owned()];
    for shadow in car_brand::shadows("card", Some(theme), Some("soft"))? {
        if shadow.inset {
            parts.push(css_shadow(&shadow));
        }
    }
    Ok(format!("--elev-tile: {};", parts.join(", ")))
}

fn designs() -> Vec<&'static str> {
    brand::DESIGNS.list().iter().map(D::s).collect()
}

/// `design_rules()`: the rules for the product's Reduce motion and each design's marks.
pub fn design_rules() -> Py<String> {
    let held = ":root[data-motion=\"reduced\"]";
    let root = |design: &str| format!(":root[data-design=\"{design}\"]");
    let mut glowless = vec![held.to_owned()];
    let mut barred = Vec::new();
    for design in designs() {
        if !car_brand::design_glow(Some(design))? {
            glowless.push(root(design));
        }
        if car_brand::design_accent_bar(Some(design))? {
            barred.push(root(design));
        }
    }
    let motion: Vec<String> = ["*", "*::before", "*::after"]
        .iter()
        .map(|part| format!("{held} {part}"))
        .collect();
    Ok([
        format!(
            "{} {{ animation: none !important; transition: none !important; }}",
            motion.join(", ")
        ),
        format!(
            "{} {{ display: none; }}",
            glowless
                .iter()
                .map(|each| format!("{each} .halo::before"))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        format!(
            "{} {{ box-shadow: inset {} 0 0 var(--accent); }}",
            barred
                .iter()
                .map(|each| format!("{each} .card"))
                .collect::<Vec<_>>()
                .join(", "),
            css::css_length(brand::ACCENT_BAR.f())
        ),
    ]
    .join("\n"))
}

/// `re.findall(r"--size-([a-z-]+-pad):\s*([^;]+);", text)`.
fn padded_sizes(text: &str) -> Vec<(String, String)> {
    let mut found = Vec::new();
    let mut at = 0;
    while let Some(offset) = text[at..].find("--size-") {
        let start = at + offset + "--size-".len();
        let name_end = text[start..]
            .find(|c: char| !(c.is_ascii_lowercase() || c == '-'))
            .map_or(text.len(), |end| start + end);
        let name = &text[start..name_end];
        let rest = &text[name_end..];
        if name.len() > 4 && name.ends_with("-pad") && rest.starts_with(':') {
            let after = &rest[1..];
            let value_start = after
                .find(|c: char| !car_machine::pytext::is_space(c))
                .unwrap_or(after.len());
            let value_text = &after[value_start..];
            if let Some(semi) = value_text.find(';') {
                let (value, whole) = if semi == 0 {
                    // `\s*` gives its last character back so `[^;]+` has one.
                    if value_start == 0 {
                        (None, 0)
                    } else {
                        let last = after[..value_start]
                            .chars()
                            .last()
                            .map_or(0, char::len_utf8);
                        (Some(&after[value_start - last..value_start]), value_start)
                    }
                } else {
                    (Some(&value_text[..semi]), value_start + semi)
                };
                if let Some(value) = value {
                    found.push((
                        name[..name.len() - "-pad".len()].to_owned() + "-pad",
                        value.to_owned(),
                    ));
                    at = name_end + 1 + whole + 1;
                    continue;
                }
            }
        }
        at = start;
    }
    found
}

/// `right_to_left_rules()`: the rules for a page written right to left.
pub fn right_to_left_rules() -> Py<String> {
    let root = ":root[dir=\"rtl\"]";
    let mut swapped = Vec::new();
    for (name, value) in padded_sizes(&css::css_scale()?) {
        let sides: Vec<&str> = value.split_whitespace().collect();
        if sides.len() == 4 && sides[1] != sides[3] {
            swapped.push(format!(
                "--size-{name}: {};",
                [sides[0], sides[3], sides[2], sides[1]].join(" ")
            ));
        }
    }
    let mut barred = Vec::new();
    for design in designs() {
        if car_brand::design_accent_bar(Some(design))? {
            barred.push(format!("{root}[data-design=\"{design}\"] .card"));
        }
    }
    let mut rules = Vec::new();
    if !swapped.is_empty() {
        rules.push(format!("{root} {{ {} }}", swapped.join(" ")));
    }
    rules.push(format!("{root} input.switch:checked::before {{ transform: translateX(calc(-1 * var(--size-knob-travel))); }}"));
    rules.push(format!(
        "{root} details.fold:not([open]) > summary .chevron {{ transform: rotate(135deg); }}"
    ));
    rules.push(format!(
        "{root} .prow-name, {root} .stored-text {{ unicode-bidi: plaintext; }}"
    ));
    rules.push(format!(
        "{root} .mono {{ direction: ltr; unicode-bidi: isolate; }}"
    ));
    if !barred.is_empty() {
        rules.push(format!(
            "{} {{ box-shadow: inset -{} 0 0 var(--accent); }}",
            barred.join(", "),
            css::css_length(brand::ACCENT_BAR.f())
        ));
    }
    Ok(rules.join("\n"))
}

fn variables(theme: &str) -> Py<String> {
    Ok(css::css_variables(&css::pairs(car_brand::palette(
        Some(theme),
        Some("soft"),
    )?)))
}

/// `_STYLE`: the stylesheet with every `@TOKEN@` filled.
pub fn style() -> Py<String> {
    let tile = |theme: &str, design: &str| tile_elevation(theme, design).unwrap_or_default();
    let mini = match brand::STATUS_DOT.find("mini") {
        Some(dot) => dot.f(),
        None => return Err("KeyError"),
    };
    let select = car_brand::padding("select_pad")?;
    Ok(STYLE_TEMPLATE
        .replace("@LIGHT@", &variables("light")?)
        .replace("@DARK@", &variables("dark")?)
        .replace("@ELEVATION_LIGHT@", &css::css_elevation(Some("light"))?)
        .replace("@ELEVATION_DARK@", &css::css_elevation(Some("dark"))?)
        .replace("@TILE_LIGHT@", &tile_elevation("light", "soft")?)
        .replace("@TILE_DARK@", &tile_elevation("dark", "soft")?)
        .replace("@DESIGNS@", &css::css_design_blocks(Some(&tile))?)
        .replace("@DESIGN_MOTION@", &design_rules()?)
        .replace("@RIGHT_TO_LEFT@", &right_to_left_rules()?)
        .replace("@SCALE@", &css::css_scale()?)
        .replace("@GLOW_KEYFRAMES@", &css::css_glow_keyframes())
        .replace("@GLOW_MINI@", &css::css_glow_geometry(mini))
        .replace(
            "@SELECT_PAD_LEFT@",
            &format!("{}px", car_brand::pyfmt::g(select[3].f())),
        ))
}

// ------------------------------------------------------------------------------------- the keys the script asks
fn word_before(text: &str, at: usize) -> bool {
    text[..at]
        .chars()
        .last()
        .is_some_and(|c| c.is_alphanumeric() || c == '_')
}

fn key_class(c: char) -> bool {
    c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '.'
}

fn skip_space(text: &str, at: usize) -> usize {
    text[at..]
        .find(|c: char| !car_machine::pytext::is_space(c))
        .map_or(text.len(), |end| at + end)
}

/// After `(` at `at`: `\s*'([a-z0-9_.]+)'` - the key and where the quote after it ends.
fn quoted_key(text: &str, at: usize) -> Option<(String, usize)> {
    let at = skip_space(text, at);
    let rest = text[at..].strip_prefix('\'')?;
    let start = at + 1;
    let end = rest
        .find(|c: char| !key_class(c))
        .map_or(text.len(), |end| start + end);
    if end == start || !text[end..].starts_with('\'') {
        return None;
    }
    Some((text[start..end].to_owned(), end + 1))
}

/// `panel_keys()`: the keys the script names, and the prefixes it builds keys from.
pub fn panel_keys() -> (Vec<String>, Vec<String>) {
    let text = SCRIPT;
    let mut names = Vec::new();
    let mut at = 0;
    // `\b(?:t|fill|withLanguage)\(\s*'([a-z0-9_.]+)'\s*[,)]`, matches taken left to right, none overlapping.
    while at < text.len() {
        let mut matched = None;
        if !word_before(text, at) {
            for call in ["t(", "fill(", "withLanguage("] {
                if text[at..].starts_with(call)
                    && let Some((key, end)) = quoted_key(text, at + call.len())
                {
                    let end = skip_space(text, end);
                    if text[end..].starts_with(',') || text[end..].starts_with(')') {
                        matched = Some((key, end + 1));
                        break;
                    }
                }
            }
        }
        match matched {
            Some((key, end)) => {
                if !names.contains(&key) {
                    names.push(key);
                }
                at = end;
            }
            None => at += text[at..].chars().next().map_or(1, char::len_utf8),
        }
    }
    let mut prefixes: Vec<String> = Vec::new();
    let mut at = 0;
    // `\b(?:t|fill)\(\s*'([a-z0-9_.]+\.)'\s*\+|\bS\['([a-z0-9_.]+\.)'\s*\+`.
    while at < text.len() {
        let mut matched = None;
        if !word_before(text, at) {
            for call in ["t(", "fill(", "S["] {
                if !text[at..].starts_with(call) {
                    continue;
                }
                let found = if call == "S[" {
                    let start = at + 2;
                    text[start..].strip_prefix('\'').and_then(|_| {
                        let begin = start + 1;
                        let end = text[begin..]
                            .find(|c: char| !key_class(c))
                            .map_or(text.len(), |end| begin + end);
                        (end > begin && text[end..].starts_with('\''))
                            .then(|| (text[begin..end].to_owned(), end + 1))
                    })
                } else {
                    quoted_key(text, at + call.len())
                };
                if let Some((key, end)) = found
                    && key.ends_with('.')
                {
                    let end = skip_space(text, end);
                    if text[end..].starts_with('+') {
                        matched = Some((key, end + 1));
                        break;
                    }
                }
            }
        }
        match matched {
            Some((key, end)) => {
                if !prefixes.contains(&key) {
                    prefixes.push(key);
                }
                at = end;
            }
            None => at += text[at..].chars().next().map_or(1, char::len_utf8),
        }
    }
    names.sort();
    prefixes.sort();
    (names, prefixes)
}

fn catalog_value(catalog: &car_words::l10n::Catalog) -> Value {
    let mut map = Map::new();
    for (key, text) in catalog {
        map.insert(Str::from(key.as_str()), Value::from(text.as_str()));
    }
    Value::Object(map)
}

/// `panel_catalogs()`: every offered language's words for this page, and only this page's.
pub fn panel_catalogs() -> Value {
    let (names, prefixes) = panel_keys();
    let mut all = Map::new();
    for locale in car_words::l10n::OFFERED {
        let mut kept = Map::new();
        for (key, text) in car_words::l10n::catalog(locale) {
            if names.contains(&key)
                || prefixes
                    .iter()
                    .any(|prefix| key.starts_with(prefix.as_str()))
            {
                kept.insert(Str::from(key.as_str()), Value::from(text.as_str()));
            }
        }
        all.insert(Str::from(*locale), Value::Object(kept));
    }
    Value::Object(all)
}

/// `"%.3f" % x` with the zeros and the point at the end taken off, and `px`.
fn length(value: f64) -> String {
    let fixed = format!("{value:.3}");
    format!("{}px", fixed.trim_end_matches('0').trim_end_matches('.'))
}

fn d_number(value: &D) -> f64 {
    value.f()
}

/// `text_scale_style(text)`: the panel at Windows' text size, or "" at the usual size.
pub fn text_scale_style(text: &Value) -> String {
    let factor = match text {
        Value::Float(x) => *x,
        Value::Int(int) => match int.as_i64() {
            Some(each) => each as f64,
            None => int.to_string().parse::<f64>().unwrap_or(f64::INFINITY),
        },
        _ => return String::new(),
    };
    if factor.is_nan() || factor <= 1.0 {
        return String::new();
    }
    let factor = factor.min(HIGHEST_TEXT / 100.0);
    let mut parts = Vec::new();
    for (name, value) in brand::TYPE_SCALE.items() {
        parts.push(format!(
            "--type-{}: {};",
            hyphens(name),
            length(d_number(value) * factor)
        ));
    }
    for name in TEXT_HOLDERS {
        let value = brand::LAYOUT.find(name).map_or(0.0, d_number);
        parts.push(format!(
            "--size-{}: {};",
            hyphens(name),
            length(value * factor)
        ));
    }
    parts.push(format!(
        "--line-control: {};",
        length(LINE_CONTROL * factor)
    ));
    format!("<style>:root {{ {} }}</style>", parts.join(" "))
}

/// `FONT_STACK`: the page's type stack, `--font`'s value with its white space made single.
pub fn font_stack(style: &str) -> String {
    let Some(at) = style.find("--font:") else {
        return String::new();
    };
    let after = &style[at + "--font:".len()..];
    let start = after
        .find(|c: char| !car_machine::pytext::is_space(c))
        .unwrap_or(after.len());
    let value = &after[start..];
    let value = &value[..value.find(';').unwrap_or(value.len())];
    value
        .split(car_machine::pytext::is_space)
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

/// `typeface_style(face)`: the offered languages the UI font cannot set whole, set in Segoe UI; "" when it sets all.
pub fn typeface_style(host: &dyn Host, face: Option<&str>, stack: &str) -> String {
    let Some(face) = face else {
        return String::new();
    };
    let lacks = |face: &str, text: &str| host.face_lacks(face, text);
    let mut whole = Vec::new();
    for locale in car_words::l10n::OFFERED {
        let catalog = car_words::l10n::catalog(locale);
        let texts: Vec<&str> = catalog.values().map(String::as_str).collect();
        let letters = car_platform::typeface::letters(&texts);
        if car_platform::typeface::face_for(face, &letters, &lacks) != face {
            whole.push(*locale);
        }
    }
    if whole.is_empty() {
        return String::new();
    }
    format!(
        "<style>{} {{ --font: \"{SEGOE}\", {stack}; }}</style>",
        whole
            .iter()
            .map(|locale| format!(":root:lang({locale})"))
            .collect::<Vec<_>>()
            .join(", ")
    )
}

/// `_script_json(value)`: the wire's JSON with `<` as `<`.
pub fn script_json(value: &Value) -> Py<String> {
    to_string(value, &Options::wire())
        .map(|text| text.replace('<', "\\u003c"))
        .map_err(|_| "ValueError")
}

fn num(value: Num) -> Value {
    match value {
        Num::I(int) => Value::from(int),
        Num::F(x) => Value::Float(x),
    }
}

/// A table value as JSON (a tuple is a list, as `json.dumps` writes it).
pub fn d_value(value: &D) -> Value {
    match value {
        D::Null => Value::Null,
        D::B(on) => Value::Bool(*on),
        D::N(number) => num(*number),
        D::S(text) => Value::from(*text),
        D::L(items) => Value::Array(items.iter().map(d_value).collect()),
        D::M(pairs) => {
            let mut map = Map::new();
            for (key, each) in pairs.iter() {
                map.insert(Str::from(*key), d_value(each));
            }
            Value::Object(map)
        }
    }
}

fn element_value(element: &days::Element) -> Value {
    Value::Array(vec![
        Value::from(element.kind.as_str()),
        Value::Array(element.numbers.iter().map(|each| num(*each)).collect()),
        Value::from(element.colour.as_str()),
        num(element.opacity),
        Value::from(element.motion.as_str()),
        Value::Array(element.values.iter().map(|each| num(*each)).collect()),
    ])
}

/// `day_data(look)`: what the page draws a special day from.
pub fn day_data(look: &str) -> Py<Value> {
    let ground = brand::DAY_LOOKS.find(look).ok_or("KeyError")?.list();
    let ground = ground.get(2).ok_or("IndexError")?;
    let focus = brand::SCENE_FOCUS.find(look).ok_or("KeyError")?;
    let from_top = brand::SCENE_FROM_TOP
        .list()
        .iter()
        .any(|each| each.s() == look);
    let wide = |key: &str| brand::WIDE.find(key).map_or(Value::Null, d_value);
    let mut map = Map::new();
    let mut put = |key: &str, value: Value| {
        map.insert(Str::from(key), value);
    };
    put("look", Value::from(look));
    put("ground", d_value(ground));
    put("focus", d_value(focus));
    put("width", d_value(&brand::SCENE_WIDTH));
    put("height", d_value(&brand::SCENE_HEIGHT));
    put("fromTop", Value::Bool(from_top));
    put(
        "elements",
        Value::Array(
            days::scene_elements(look)?
                .iter()
                .map(element_value)
                .collect(),
        ),
    );
    put(
        "specks",
        Value::Array(
            days::speck_elements(look)?
                .iter()
                .map(element_value)
                .collect(),
        ),
    );
    put(
        "speckReach",
        Value::Array(
            days::speck_reach(look)?
                .iter()
                .map(|(a, b)| Value::Array(vec![num(*a), num(*b)]))
                .collect(),
        ),
    );
    put("speckBand", d_value(&brand::SPECK_BAND));
    put(
        "wide",
        Value::Object({
            let mut wide_map = Map::new();
            wide_map.insert(Str::from("gap"), wide("gap"));
            wide_map.insert(Str::from("fade"), wide("fade"));
            wide_map
        }),
    );
    Ok(Value::Object(map))
}

/// `brand.day_look_at(moment)`: the look of the local date at `moment`, on the Host's local clock.
pub fn day_look_at(host: &dyn Host, moment: f64) -> Option<String> {
    let local = host.local_clock().localtime(moment).ok()?;
    days::day_look(local.year, local.mon, local.mday).map(str::to_owned)
}

/// What `settings_page` is asked for: every argument of the reference's, the server passing only `day`.
#[derive(Clone, Debug, Default)]
pub struct Page {
    /// A preview's seed data (`data`).
    pub data: Option<Value>,
    pub theme: Option<String>,
    pub design: Option<String>,
    /// Windows' text size, asked of the Host when None.
    pub text: Option<Value>,
    /// Windows' UI font: `Some(None)` is a face that cannot be asked, None asks the Host.
    pub face: Option<Option<String>>,
    pub day: Option<String>,
}

/// `settings_page(data, theme, design, text, face, day)`: the panel as one HTML document.
pub fn settings_page(host: &dyn Host, page: &Page) -> Py<String> {
    let environ = |name: &str| host.environ(name);
    let windows = || host.windows_languages();
    let locale = car_words::interface::language(&environ, &windows);
    let catalog = format!(
        "<script>window.__CODEX_AUTO_RESUME_STRINGS__={};</script>",
        script_json(&catalog_value(&car_words::l10n::catalog(locale)))?
    );
    let mut right_to_left: Vec<&str> = car_words::l10n::RIGHT_TO_LEFT.to_vec();
    right_to_left.sort();
    let sweep = {
        let mut map = Map::new();
        map.insert(Str::from("presses"), d_value(&brand::PRESSES));
        map.insert(Str::from("sweep"), d_value(&brand::SWEEP));
        map.insert(Str::from("head"), d_value(&brand::ICON_ACCENT));
        Value::Object(map)
    };
    let mut catalogs = format!(
        "<script>window.__CODEX_AUTO_RESUME_LOCALE__={};window.__CODEX_AUTO_RESUME_CATALOGS__={};window.__CODEX_AUTO_RESUME_RTL__={};window.__CODEX_AUTO_RESUME_SWEEP__={};</script>",
        script_json(&Value::from(locale))?,
        script_json(&panel_catalogs())?,
        script_json(&Value::Array(
            right_to_left
                .iter()
                .map(|each| Value::from(*each))
                .collect()
        ))?,
        script_json(&sweep)?
    );
    if let Some(day) = &page.day {
        catalogs.push_str(&format!(
            "<script>window.__CODEX_AUTO_RESUME_DAY__={};</script>",
            script_json(&day_data(day)?)?
        ));
    }
    let seed = match &page.data {
        Some(data) => format!(
            "<script>window.__CODEX_AUTO_RESUME__={};</script>",
            script_json(data)?
        ),
        None => String::new(),
    };
    let mut root = match page.theme.as_deref() {
        Some(theme @ ("light" | "dark")) => {
            format!("<html data-theme=\"{theme}\" data-theme-pinned=\"\">")
        }
        _ => "<html>".to_owned(),
    };
    if let Some(design) = page.design.as_deref()
        && designs().contains(&design)
    {
        let stamp = if design == brand::DEFAULT_DESIGN.s() {
            String::new()
        } else {
            format!(" data-design=\"{design}\"")
        };
        root.pop();
        root = format!("{root}{stamp} data-design-pinned=\"\">");
    }
    let style = style()?;
    let text = page.text.clone().unwrap_or_else(|| host.text_size());
    let face = match &page.face {
        Some(face) => face.clone(),
        None => host.ui_face(),
    };
    let stack = font_stack(&style);
    Ok(format!(
        "<!doctype html>{root}<head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Codex Auto Resume</title><style>{style}</style>{}{}</head><body><div id=\"root\"></div>{catalog}{catalogs}{seed}<script>{SCRIPT}</script></body></html>",
        text_scale_style(&text),
        typeface_style(host, face.as_deref(), &stack)
    ))
}
