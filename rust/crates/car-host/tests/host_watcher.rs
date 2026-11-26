//! The six exports over a real watcher, as the C# host drives them (P6-DESIGN 1.2, 1.5), on a scratch home: start,
//! the `surfaces` event with the catalog's locale and letters, a snapshot carrying the popup's view and the icon's
//! three answers, the in-process bridge, a popup call and a seen failure through `car_post_action`, a second start
//! refused, the stop, `close` and `ended` last.

mod common;

use car_machine::json::Value;
use common::*;

#[test]
fn the_exports_drive_one_watcher_from_start_to_ended() {
    let scratch = scratch("watcher", None);
    let home = scratch.home.clone();
    assert_eq!(
        start(&start_request(&home)),
        r#"{"abi": 1, "ok": true}"#,
        "the watcher starts"
    );
    assert_eq!(
        start(&start_request(&home)),
        r#"{"abi": 1, "ok": false, "error": "bad_request"}"#,
        "one process hosts one watcher"
    );
    let seen = pump(
        |seen| seen.iter().any(|event| kind(event) == "snapshot"),
        60,
    );
    let surfaces = seen.first().expect("an event");
    assert_eq!(kind(surfaces), "surfaces", "{seen:?}");
    assert_eq!(
        keys(surfaces),
        [
            "kind", "icon", "strings", "settings", "edition", "demo", "locale", "letters"
        ]
    );
    assert_eq!(text(surfaces, "locale"), "en");
    assert_eq!(
        text(surfaces, "letters"),
        car_watcher::surface::letters_of("en")
    );
    assert_eq!(text(surfaces, "edition"), "standard");
    let snapshot = seen.last().expect("a snapshot");
    assert_eq!(keys(snapshot), ["kind", "snapshot", "popup"]);
    let tray = get(snapshot, "snapshot");
    for key in [
        "failure_unseen",
        "unconfirmed_unseen",
        "power_armed",
        "blocked",
    ] {
        assert!(keys(tray).contains(&key.to_owned()), "{key}: {tray:?}");
    }
    assert_eq!(get(tray, "failure_unseen"), &Value::Bool(false));
    assert_eq!(get(tray, "power_armed"), &Value::Null);
    let popup = get(snapshot, "popup");
    assert_eq!(keys(popup), ["view", "menus", "read", "attention"]);
    assert_eq!(get(popup, "read"), &Value::Bool(true));
    assert!(matches!(get(popup, "view"), Value::Object(_)), "{popup:?}");

    // The in-process bridge answers as `bridge serve` does.
    let reply = bridge(r#"{"id": 7, "command": "get_status"}"#);
    assert!(reply.starts_with(r#"{"id": 7, "reply": "#), "{reply}");

    // A popup call and a seen failure, each followed at once by a snapshot.
    let answer = post(r#"{"action": "popup", "call": "set_enabled", "args": [false]}"#);
    assert_eq!(get(&answer, "ok"), &Value::Bool(true), "{answer:?}");
    let answer = post(r#"{"action": "failure_seen"}"#);
    assert_eq!(get(&answer, "ok"), &Value::Bool(true), "{answer:?}");
    let after = pump(
        |seen| {
            seen.iter()
                .filter(|event| kind(event) == "snapshot")
                .count()
                >= 2
        },
        30,
    );
    let first = after
        .iter()
        .find(|event| kind(event) == "snapshot")
        .expect("a snapshot after the click");
    assert_eq!(
        get(get(get(first, "popup"), "view"), "paused"),
        &Value::Bool(true),
        "the click's outcome is drawn: {first:?}"
    );
    // `open_chat`: a value that is not a conversation's UUID is refused before anything is started; a UUID with no
    // Dashboard beside this scratch home starts nothing either; `notice_complete` waits for the card route.
    let answer = post(r#"{"action": "open_chat", "thread": "t"}"#);
    assert_eq!(text(&answer, "error"), "not a conversation");
    let answer =
        post(r#"{"action": "open_chat", "thread": "123e4567-e89b-12d3-a456-426614174000"}"#);
    assert_eq!(get(&answer, "ok"), &Value::Bool(false));
    assert_eq!(get(&answer, "error"), &Value::Null);
    let answer = post(r#"{"action": "open_dashboard", "page": "nowhere"}"#);
    assert_eq!(text(&answer, "error"), "not a page of the window");
    let answer = post(r#"{"action": "notice_complete", "id": 1, "shown": true}"#);
    assert_eq!(text(&answer, "error"), "not_ported");

    // The stop: close, then ended last.
    // SAFETY: no argument.
    assert_eq!(car_core::car_stop(), 0);
    let end = pump(|seen| seen.iter().any(|event| kind(event) == "ended"), 60);
    let names: Vec<String> = end.iter().map(kind).collect();
    assert!(names.contains(&"close".to_owned()), "{names:?}");
    assert_eq!(names.last().map(String::as_str), Some("ended"), "{names:?}");
    assert_eq!(
        get(end.last().expect("ended"), "exit_code"),
        &Value::from(0)
    );
    assert!(next_event(50).is_none(), "nothing after ended");
    let log = log(&home);
    assert!(log.contains("watcher started (pid"), "{log}");
    // The engine join: the product's maker reached discovery, which refused the named codex.exe that is not there.
    assert!(
        log.contains("initialising Codex adapter failed (ConfigError)"),
        "{log}"
    );
    assert!(!log.contains("EngineNotJoined"), "{log}");
    assert!(log.contains("stop requested; watcher exiting"), "{log}");
}
