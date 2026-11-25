//! fix8 (REVIEW-surface.md N4): the four functions no S6.0 diff fed - the launch error's class, the presence
//! snapshot's pass-through, the card's slide and `notify::shown` - each against what the reference's line says.

use car_machine::json::{Map, Value};
use car_platform::spawn::SpawnError;
use car_surface::notice_card::CardMotion;
use car_surface::notice_presence::snapshot;
use car_surface::notify::shown;
use car_surface::seam::{Presence, launch_error};

struct Fixed;

impl Presence for Fixed {
    fn snapshot(&self, aumid: &str) -> Map {
        let mut map = Map::new();
        map.insert("notification_state".into(), Value::from(aumid));
        map.insert("screen_reader".into(), Value::Null);
        map
    }
    fn battery_saver(&self) -> bool {
        false
    }
    fn message_duration_ms(&self) -> Option<i64> {
        None
    }
}

#[test]
fn a_launch_that_fails_is_the_class_popen_raises() {
    let refused = SpawnError::Os(std::io::Error::from(std::io::ErrorKind::NotFound));
    assert_eq!(launch_error(&refused), "OSError");
    assert_eq!(launch_error(&SpawnError::Timeout), "TimeoutExpired");
}

#[test]
fn the_snapshot_is_what_the_platform_answered_for_that_identity() {
    let answer = snapshot(&Fixed, "Example.Aumid");
    assert_eq!(answer.len(), 2);
    assert_eq!(
        answer.get("notification_state"),
        Some(&Value::from("Example.Aumid"))
    );
    assert_eq!(answer.get("screen_reader"), Some(&Value::Null));
}

#[test]
fn the_slide_is_where_the_card_glides_from_and_to_until_it_arrives() {
    let mut card = CardMotion::new(0.0, 6000.0, false, Some(vec![10, 20]));
    assert_eq!(card.slide(), None);
    card.move_to(1000.0, vec![10, 120], 50.0);
    assert_eq!(card.slide(), Some((vec![10, 20], vec![10, 120], 1050.0)));
    // A reduced-motion card never glides.
    let mut still = CardMotion::new(0.0, 6000.0, true, Some(vec![10, 20]));
    still.move_to(1000.0, vec![10, 120], 0.0);
    assert_eq!(still.slide(), None);
    // The glide ends once its time is past: `place` clears it.
    assert_eq!(card.place(1e9), Some(vec![10, 120]));
    assert_eq!(card.slide(), None);
}

#[test]
fn shown_is_str_of_the_value() {
    assert_eq!(shown(&Value::Null), "None");
    assert_eq!(shown(&Value::Bool(true)), "True");
    assert_eq!(shown(&Value::from("a b")), "a b");
    assert_eq!(shown(&Value::from(7)), "7");
    assert_eq!(
        shown(&Value::Array(vec![Value::from("x"), Value::from(1)])),
        "['x', 1]"
    );
}
