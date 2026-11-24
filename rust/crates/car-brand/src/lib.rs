//! car-brand: the one place a colour is decided (PLAN 1.2 row 3) - the palette, the scale, the designs, the
//! motion curve, the shadows, the check box, the status light, the mark and its rasteriser, the corner's shape, the
//! special days, the panel's CSS and the generator of gui/Brand.cs.
//!
//! Replaces `src/codex_auto_resume/brand/` (tokens, colour, scale, design, motion, elevation, checkbox, light, mark,
//! shape, css, days and the front `__init__`) and `build/make_brand.py`, with the parts of `ui/tray/motion.py` that
//! gui/Brand.cs is made from (`tray_motion`). The tables are the tag's own, generated (tables_gen.rs, by
//! tests/rustdiff/gen_brand.py); the arithmetic is written as the Python writes it, operation for operation, so a
//! float answer is the same double - `pyfmt` holds Python's formatting and the few functions whose C library or
//! CPython versions Rust lacks (`math.hypot`, `math.erfc`). Held to the reference tag by
//! `tests/rustdiff/diffs_leaves_brand.py`.
//!
//! Pure std: no dependency. A fallible call answers `Py<T>`, the error being the Python exception's class name.

pub mod checkbox;
pub mod colour;
pub mod css;
pub mod data;
pub mod days;
pub mod design;
pub mod elevation;
pub mod light;
pub mod make_brand;
pub mod mark;
pub mod motion;
pub mod pyfmt;
pub mod scale;
pub mod shape;
#[rustfmt::skip]
pub mod tables_gen;
pub mod tokens;
pub mod tray_motion;

/// A result whose error is the name of the exception the Python raises.
pub type Py<T> = Result<T, &'static str>;

pub use colour::{brighten, contrast, luminance, mix, rgb};
pub use css::{
    css_check_box, css_design_blocks, css_ease, css_elevation, css_glow_geometry,
    css_glow_keyframes, css_scale, css_variables,
};
pub use days::{
    day_look, element_at, mark_colour, mark_text, scene_elements, scene_frame, scene_text,
    speck_elements, speck_frame, speck_text, sweep_at,
};
pub use design::{design_accent_bar, design_depth, design_glow, design_radii};
pub use elevation::{card_ground, elevation_colour, reach, shadow_alpha, shadow_offset, shadows};
pub use light::{
    glow, glow_extent, glow_floor, glow_moves, glow_phase, glow_radius, glow_reach, glow_stops,
    status_colour, status_fill, status_system,
};
pub use make_brand::render;
pub use mark::{
    icon_head_box, icon_head_centre, icon_pixel, icon_render, icon_ring_arc, icon_rounded_square,
    icon_samples,
};
pub use motion::ease;
pub use scale::padding;
pub use tokens::{design_name, palette, theme_name};
