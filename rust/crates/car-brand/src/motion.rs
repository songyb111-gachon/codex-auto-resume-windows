//! How long a change takes, and the one curve it takes it on (brand/motion.py): CSS's cubic-bezier, solved the
//! way a browser solves it.

pub use crate::tables_gen::MOTION;

/// One coordinate of a CSS cubic-bezier from (0, 0) to (1, 1) through control values a and b (`_bezier`).
pub fn bezier(a: f64, b: f64, t: f64) -> f64 {
    ((1.0 - 3.0 * b + 3.0 * a) * t + (3.0 * b - 6.0 * a)) * t * t + 3.0 * a * t
}

fn bezier_slope(a: f64, b: f64, t: f64) -> f64 {
    3.0 * (1.0 - 3.0 * b + 3.0 * a) * t * t + 2.0 * (3.0 * b - 6.0 * a) * t + 3.0 * a
}

/// `ease(progress)`: how far a transition has come, 0 to 1, after `progress` of its time, on MOTION's curve.
pub fn ease(progress: f64) -> f64 {
    if progress.partial_cmp(&0.0) != Some(std::cmp::Ordering::Greater) {
        return 0.0;
    }
    if progress >= 1.0 {
        return 1.0;
    }
    let curve = MOTION.at("ease").list();
    let (x1, y1, x2, y2) = (curve[0].f(), curve[1].f(), curve[2].f(), curve[3].f());
    let mut t = progress;
    for _ in 0..8 {
        let error = bezier(x1, x2, t) - progress;
        if error.abs() < 1e-7 {
            return bezier(y1, y2, t);
        }
        let slope = bezier_slope(x1, x2, t);
        if slope.abs() < 1e-6 {
            break;
        }
        t = crate::pyfmt::min(1.0, crate::pyfmt::max(0.0, t - error / slope));
    }
    let (mut low, mut high) = (0.0, 1.0);
    t = progress;
    for _ in 0..40 {
        let value = bezier(x1, x2, t);
        if (value - progress).abs() < 1e-7 {
            break;
        }
        if value < progress {
            low = t;
        } else {
            high = t;
        }
        t = (low + high) / 2.0;
    }
    bezier(y1, y2, t)
}
