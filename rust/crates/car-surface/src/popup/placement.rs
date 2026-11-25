//! `ui/popup/placement.py`'s placement, which the card's stack reads (`notice_card::stack_positions`): beside the
//! notification area, on the monitor the icon is on, cut to the work area, never over the taskbar. Rectangles are
//! (left, top, right, bottom) in physical pixels, negative on a monitor left of or above the primary one.

/// A rectangle: left, top, right, bottom.
pub type Rect = [i64; 4];

/// `taskbar_edge(work, monitor, anchor)`: which edge of the monitor the taskbar is on.
pub fn taskbar_edge(work: Rect, monitor: Rect, anchor: Option<Rect>) -> &'static str {
    if work[3] < monitor[3] {
        return "bottom";
    }
    if work[1] > monitor[1] {
        return "top";
    }
    if work[0] > monitor[0] {
        return "left";
    }
    if work[2] < monitor[2] {
        return "right";
    }
    if let Some(anchor) = anchor {
        // An auto-hidden taskbar takes no work area; the icon is on the nearest edge (the first of the nearest).
        let cx = (anchor[0] + anchor[2]) as f64 / 2.0;
        let cy = (anchor[1] + anchor[3]) as f64 / 2.0;
        let distances = [
            ("bottom", monitor[3] as f64 - cy),
            ("top", cy - monitor[1] as f64),
            ("left", cx - monitor[0] as f64),
            ("right", monitor[2] as f64 - cx),
        ];
        let mut best = distances[0];
        for each in &distances[1..] {
            if each.1 < best.1 {
                best = *each;
            }
        }
        return best.0;
    }
    "bottom"
}

/// `_clamp(value, low, high)`.
pub fn clamp(value: i64, low: i64, high: i64) -> i64 {
    if high < low {
        return low;
    }
    low.max(value.min(high))
}

/// `place(size, work, monitor, icon, cursor, gap)`: where the window goes, (x, y, edge).
pub fn place(
    size: (i64, i64),
    work: Rect,
    monitor: Rect,
    icon: Option<Rect>,
    cursor: Option<(i64, i64)>,
    gap: i64,
) -> (i64, i64, &'static str) {
    let (width, height) = size;
    let mut anchor = icon;
    if anchor.is_none()
        && let Some((x, y)) = cursor
    {
        anchor = Some([x, y, x + 1, y + 1]);
    }
    let edge = taskbar_edge(work, monitor, anchor);
    let [left, top, right, bottom] = work;
    let anchor = anchor.unwrap_or([right - 1, bottom - 1, right, bottom]);
    let cx = (anchor[0] + anchor[2]).div_euclid(2);
    let cy = (anchor[1] + anchor[3]).div_euclid(2);
    let (x, y) = match edge {
        "bottom" => (
            cx - width.div_euclid(2),
            anchor[1].min(bottom) - gap - height,
        ),
        "top" => (cx - width.div_euclid(2), anchor[3].max(top) + gap),
        "left" => (anchor[2].max(left) + gap, cy - height.div_euclid(2)),
        _ => (
            anchor[0].min(right) - gap - width,
            cy - height.div_euclid(2),
        ),
    };
    let x = clamp(x, left + gap, right - gap - width);
    let y = clamp(y, top + gap, bottom - gap - height);
    (x, y, edge)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn beside_the_icon() {
        let work = [0, 0, 1920, 1040];
        let monitor = [0, 0, 1920, 1080];
        assert_eq!(taskbar_edge(work, monitor, None), "bottom");
        let (x, y, edge) = place(
            (360, 200),
            work,
            monitor,
            Some([1800, 1050, 1824, 1074]),
            None,
            12,
        );
        assert_eq!((x, y, edge), (1548, 828, "bottom"));
        assert_eq!(
            taskbar_edge(monitor, monitor, Some([0, 500, 10, 510])),
            "left"
        );
    }
}
