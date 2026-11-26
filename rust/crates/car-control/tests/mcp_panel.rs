//! The panel's pieces build (S5.2): each `@TOKEN@` of the stylesheet is filled from car-brand without an error.

use car_control::mcp::panel;

#[test]
fn every_piece_of_the_stylesheet_builds() {
    for theme in ["light", "dark"] {
        for design in ["soft", "classic", "plain"] {
            panel::tile_elevation(theme, design)
                .unwrap_or_else(|class| panic!("tile {theme} {design}: {class}"));
        }
    }
    panel::design_rules().unwrap_or_else(|class| panic!("design rules: {class}"));
    panel::right_to_left_rules().unwrap_or_else(|class| panic!("right to left: {class}"));
    let style = panel::style().unwrap_or_else(|class| panic!("style: {class}"));
    assert!(!style.contains("@LIGHT@") && !style.contains("@SCALE@"));
    assert!(!panel::font_stack(&style).is_empty());
    let (names, prefixes) = panel::panel_keys();
    assert!(!names.is_empty() && !prefixes.is_empty());
}
