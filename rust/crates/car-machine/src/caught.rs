//! D15's one panic catcher (Integration 7): `try: body() except Exception` for a panic as well as an error, shared by
//! every crate that holds a boundary where the reference catches an exception - car-scheduler's `caught` and
//! car-engine's wrapped seams (`caught.rs`), car-surface's `seam::caught`, and the hosts of a port that panics with
//! [`Raised`]. It sits here because car-machine is the one crate all of them may name (PLAN 1.3).
//!
//! What each boundary answers is still its own (the engine's `Err("Exception")`, the surface's `Raised` with a class,
//! an attribute's `None`); this module gives them the one way to catch and the one way to read what a panic carried.

use std::any::Any;
use std::panic::{AssertUnwindSafe, catch_unwind};

/// What a panic carries.
pub type Payload = Box<dyn Any + Send>;

/// An exception the port raises as a panic, where a seam's result cannot carry it: the exception's class and its
/// text (a port's `TypeError` of the wire). A boundary reads it with [`raised`] or [`class_of`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Raised {
    pub class: &'static str,
    pub message: String,
}

/// `body()`, its panic caught: the value, or what the panic carried.
pub fn catch<T>(body: impl FnOnce() -> T) -> Result<T, Payload> {
    catch_unwind(AssertUnwindSafe(body))
}

/// `try: body() except Exception as error: answer(error)`: an `Err` is the body's own; a panic is `as_error` of what
/// it carried.
pub fn caught<T, E>(
    body: impl FnOnce() -> Result<T, E>,
    as_error: impl FnOnce(Payload) -> E,
) -> Result<T, E> {
    catch(body).unwrap_or_else(|payload| Err(as_error(payload)))
}

/// The [`Raised`] a panic carried, or None for a panic of the port's own.
pub fn raised(payload: &(dyn Any + Send)) -> Option<&Raised> {
    payload.downcast_ref::<Raised>()
}

/// The class of the exception a panic stands for, as Python names it: a [`Raised`]'s own; a text of the form
/// `ClassName: ...` whose name is a Python exception's (ASCII letters and digits, ending in `Error` or `Exception`);
/// else `Exception`.
pub fn class_of(payload: &(dyn Any + Send)) -> String {
    if let Some(raised) = raised(payload) {
        return raised.class.to_owned();
    }
    let text = payload
        .downcast_ref::<&str>()
        .map(|text| (*text).to_owned())
        .or_else(|| payload.downcast_ref::<String>().cloned());
    text.as_deref()
        .and_then(|text| text.split_once(':'))
        .map(|(name, _)| name)
        .filter(|name| {
            (name.ends_with("Error") || name.ends_with("Exception"))
                && name.chars().all(|c| c.is_ascii_alphanumeric())
        })
        .unwrap_or("Exception")
        .to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_panic_is_the_error_its_boundary_makes_of_it() {
        let ok: Result<i32, String> = caught(|| Ok(1), |_| "never".into());
        assert_eq!(ok, Ok(1));
        let err: Result<i32, String> = caught(|| Err("its own".into()), |_| "never".into());
        assert_eq!(err, Err("its own".to_owned()));
        let panicked: Result<i32, String> = caught(|| panic!("OSError: gone"), |p| class_of(&*p));
        assert_eq!(panicked, Err("OSError".to_owned()));
    }

    #[test]
    fn the_class_is_the_payloads_own_or_exception() {
        let class = |body: fn()| class_of(&*catch(body).expect_err("it panics"));
        assert_eq!(class(|| panic!("ValueError: no")), "ValueError");
        assert_eq!(
            class(|| panic!("{}", String::from("KeyError: 'x'"))),
            "KeyError"
        );
        assert_eq!(class(|| panic!("not a class: text")), "Exception");
        assert_eq!(class(|| panic!("Bad Error: spaced")), "Exception");
        assert_eq!(class(|| panic!("no colon")), "Exception");
        assert_eq!(
            class(|| std::panic::panic_any(Raised {
                class: "TypeError",
                message: "unhashable type: 'list'".into(),
            })),
            "TypeError"
        );
        assert_eq!(class(|| std::panic::panic_any(7_u8)), "Exception");
        let other = catch(|| panic!("the port's own")).expect_err("it panics");
        assert!(raised(&*other).is_none());
    }
}
