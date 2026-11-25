//! `registry.py`: the capability registry - every capability this edition can offer, and what each one is.
//!
//! A capability is a definition here plus its code. The definition says everything a person is asked to agree to and
//! everything the plug holds it to: its id, kind, the plug points it answers at, the revision of its statement, the standards
//! it departs from (never empty), the Compatibility Registry capability it stands on, the measurements its route rests on
//! (`measurements`, and `narrowed_by` for the part), its ceilings, its choices (`OptionDef`), the rules editor and samples, its
//! journal prefix and codes, whether it resends, what it requires and the wordings it keeps.
//!
//! The definitions of what the edition ships are generated (`registry_gen.rs`, from `registry.DEFINITIONS`, `WAITING`,
//! `INSTALLED_ONLY` and `SHOWN_ORDER` of the reference tag); the rules a definition must keep (`problems`), the registry that
//! refuses one that breaks them (`Registry`), what it needs (`requires`, `required_by`), who answers at a point (`at`), the order
//! a person sees them in (`shown`) and which hidden ones a table of measurements lets out (`offered`) are ported from the tag.
//!
//! `make` - the factory for a capability's code - is not here: it is the plug's (S7.2). The plug maps an id to its code, and
//! the registry says nothing of it. The one other thing the tag's module reads from the machine, `on_an_installation` (whether
//! `runtime\python.exe` stands beside the source), is a flag the host hands in.

use std::collections::{BTreeSet, HashMap};

use car_policy::plug::Point;

use crate::measured::{self, Table};
use crate::standards;
use crate::vocabulary::{CapabilityKind, Measurement, OptionKey, Verdict, WordingKey};

pub use crate::registry_gen::{CORE_COOLDOWN_SECONDS, CORE_DAILY_CAP, GLOBAL_HOURLY, SHOWN_ORDER};

/// `owned(&["a", "b"])`: the generated tables' lists of words.
pub fn owned(items: &[&str]) -> Vec<String> {
    items.iter().map(|each| (*each).to_owned()).collect()
}

/// `CAPABILITY_POINTS`: the points a capability's code may answer at - all but the plug's own: the claim ledger, the surfaces
/// and the moves core tells of.
pub fn capability_points() -> BTreeSet<Point> {
    Point::ALL
        .iter()
        .copied()
        .filter(|point| !matches!(point, Point::ClaimLedger | Point::Surfaces | Point::Moved))
        .collect()
}

fn fullmatch(
    text: &str,
    first: impl Fn(char) -> bool,
    rest: impl Fn(char) -> bool,
    min: usize,
    max: usize,
) -> bool {
    let mut chars = text.chars();
    let Some(head) = chars.next() else {
        return false;
    };
    let tail: Vec<char> = chars.collect();
    first(head) && (min..=max).contains(&(tail.len() + 1)) && tail.iter().all(|each| rest(*each))
}

fn lower(each: char) -> bool {
    each.is_ascii_lowercase()
}

fn lower_digit_underscore(each: char) -> bool {
    each.is_ascii_lowercase() || each.is_ascii_digit() || each == '_'
}

/// `ID_SHAPE.fullmatch`: `[a-z][a-z0-9_]{2,47}`.
pub fn id_shape(text: &str) -> bool {
    fullmatch(text, lower, lower_digit_underscore, 3, 48)
}

/// `PREFIX_SHAPE.fullmatch`: `[a-z]{2,8}`.
pub fn prefix_shape(text: &str) -> bool {
    fullmatch(text, lower, lower, 2, 8)
}

/// `CODE_SHAPE.fullmatch`: `[a-z][a-z0-9_]{0,31}`.
pub fn code_shape(text: &str) -> bool {
    fullmatch(text, lower, lower_digit_underscore, 1, 32)
}

/// `RegistryError`: a definition that breaks a rule of the registry. Raised when the registry is made.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RegistryError(pub String);

impl std::fmt::Display for RegistryError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for RegistryError {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Ceilings {
    /// This capability's sends in 24 hours, every conversation together.
    pub per_day: i64,
    /// Its sends in 24 hours in any one conversation.
    pub per_conversation: i64,
}

/// A choice a capability offers a person.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OptionDef {
    pub key: OptionKey,
    /// The values it may take: whole numbers from 1, smallest first.
    pub choices: Vec<i64>,
    /// The one it has until a person picks another; one of the choices.
    pub default: i64,
    /// (lowest, highest) a person may type in beside the choices, or `None` where only the choices are taken.
    pub custom: Option<(i64, i64)>,
}

impl OptionDef {
    /// `takes(value)`: one of its choices, or a whole number in its custom range.
    pub fn takes(&self, value: i64) -> bool {
        self.choices.contains(&value)
            || self
                .custom
                .is_some_and(|(low, high)| low <= value && value <= high)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CapabilityDef {
    pub id: String,
    pub kind: CapabilityKind,
    pub points: Vec<Point>,
    pub revision: i64,
    pub departs_from: Vec<String>,
    /// `None` for an action, which stands on none.
    pub compat: Option<String>,
    /// `None` for an action, which spends nothing.
    pub ceilings: Option<Ceilings>,
    pub journal_prefix: String,
    pub codes: Vec<String>,
    pub measurements: Vec<Measurement>,
    pub options: Vec<OptionDef>,
    pub rules_editor: bool,
    pub samples: bool,
    pub resends: bool,
    pub requires: Vec<String>,
    pub wordings: Vec<WordingKey>,
    pub narrowed_by: Vec<Measurement>,
    /// Whether it sends to Codex where none of its points is a sending one, or `None`: its points decide.
    pub sends: Option<bool>,
}

impl CapabilityDef {
    /// `definition.points` as the frozenset it is.
    pub fn point_set(&self) -> BTreeSet<Point> {
        self.points.iter().copied().collect()
    }

    pub fn answers_at(&self, point: Point) -> bool {
        self.points.contains(&point)
    }

    /// `option(key)`: the choice of `key` this capability offers, or `None`.
    pub fn option(&self, key: OptionKey) -> Option<&OptionDef> {
        self.options.iter().find(|option| option.key == key)
    }

    /// `code(word)`: `word` as this capability's journal writes it, or `None` if it is not one of its own.
    pub fn code(&self, word: &str) -> Option<String> {
        self.codes
            .iter()
            .any(|code| code == word)
            .then(|| format!("{}.{word}", self.journal_prefix))
    }
}

fn count(value: i64) -> bool {
    value >= 1
}

fn option_problem(option: &OptionDef) -> bool {
    let sorted: BTreeSet<i64> = option.choices.iter().copied().collect();
    let in_order = option.choices.len() == sorted.len()
        && option.choices.iter().copied().eq(sorted.iter().copied());
    option.choices.is_empty()
        || !option.choices.iter().all(|value| count(*value))
        || !in_order
        || !count(option.default)
        || !option.choices.contains(&option.default)
        || !option.custom.is_none_or(|(low, high)| {
            count(low)
                && count(high)
                && low <= option.choices[0]
                && option.choices[option.choices.len() - 1] <= high
        })
}

/// `problems(definition)`: every rule `definition` breaks, each named in a few words. Empty when it keeps them all.
pub fn problems(definition: &CapabilityDef) -> Vec<String> {
    let mut found: Vec<String> = Vec::new();
    let mut add = |text: &str| found.push(text.to_owned());
    if !id_shape(&definition.id) {
        add("id");
    }
    let action = definition.kind == CapabilityKind::Action;
    let points = definition.point_set();
    if action {
        if !points.is_empty() {
            add("an action answers at no point");
        }
        if definition.compat.is_some() {
            add("an action stands on no compatibility capability");
        }
        if definition.ceilings.is_some() {
            add("an action has no ceilings: it spends nothing");
        }
        if !definition.measurements.is_empty() || !definition.narrowed_by.is_empty() {
            add("an action rests on no measurement");
        }
    } else if points.is_empty() {
        add("points");
    } else if !points.is_subset(&capability_points()) {
        add("points the plug keeps for itself");
    }
    if !count(definition.revision) {
        add("revision");
    }
    let departs = &definition.departs_from;
    if departs.is_empty() {
        add("departs_from is empty: it keeps every standard, so it is standard");
    } else {
        let unique: BTreeSet<&String> = departs.iter().collect();
        if unique.len() != departs.len()
            || !departs
                .iter()
                .all(|standard| standards::declarable_set().contains(standard.as_str()))
        {
            add("departs_from names a standard the standard edition does not keep");
        }
    }
    if !action {
        if !definition.compat.as_deref().is_some_and(id_shape) {
            add("compat");
        }
        let broken = match definition.ceilings {
            None => true,
            Some(ceilings) => {
                !count(ceilings.per_day)
                    || !count(ceilings.per_conversation)
                    || ceilings.per_conversation > ceilings.per_day
                    || (ceilings.per_conversation > CORE_DAILY_CAP
                        && !departs.iter().any(|standard| standard == "A20"))
                    || ceilings.per_day > GLOBAL_HOURLY * 24
            }
        };
        if broken {
            add("ceilings");
        }
    }
    if !prefix_shape(&definition.journal_prefix) {
        add("journal_prefix");
    }
    let codes: BTreeSet<&String> = definition.codes.iter().collect();
    if !definition.codes.iter().all(|code| code_shape(code))
        || codes.len() != definition.codes.len()
    {
        add("codes");
    }
    let measurements: BTreeSet<Measurement> = definition.measurements.iter().copied().collect();
    if measurements.len() != definition.measurements.len() {
        add("measurements");
    }
    let narrowed: BTreeSet<Measurement> = definition.narrowed_by.iter().copied().collect();
    if narrowed.len() != definition.narrowed_by.len() || !narrowed.is_disjoint(&measurements) {
        add("narrowed_by");
    }
    let keys: BTreeSet<OptionKey> = definition.options.iter().map(|option| option.key).collect();
    if definition.options.iter().any(option_problem) || keys.len() != definition.options.len() {
        add("options");
    }
    if definition.resends && !points.contains(&Point::Schedule) {
        add("resends");
    }
    // v0.6.22: P22 is asked while recovery is paused, so answering there says the capability sends nothing to Codex: a
    // resident answers at P8 and P22 alone, never at a point that decides or sends.
    if points.contains(&Point::Resident)
        && !points
            .iter()
            .all(|point| matches!(point, Point::Tick | Point::Resident))
    {
        add("a resident answers at P8 and P22 alone: it sends nothing to Codex");
    }
    let requires: BTreeSet<&String> = definition.requires.iter().collect();
    if requires.len() != definition.requires.len() || definition.requires.contains(&definition.id) {
        add("requires");
    }
    found
}

/// A closed set of capabilities: the ids it was made with, and no others, ever. Anything a table or a surface holds under an id
/// the registry does not know is not one of these, and is never evaluated.
#[derive(Clone, Debug)]
pub struct Registry {
    pub definitions: Vec<CapabilityDef>,
    by_id: HashMap<String, usize>,
}

impl Registry {
    pub fn new(definitions: Vec<CapabilityDef>) -> Result<Registry, RegistryError> {
        for definition in &definitions {
            let found = problems(definition);
            if !found.is_empty() {
                return Err(RegistryError(format!(
                    "{}: {}",
                    definition.id,
                    found.join("; ")
                )));
            }
        }
        for attribute in ["id", "journal_prefix"] {
            let values: Vec<&String> = definitions
                .iter()
                .map(|each| {
                    if attribute == "id" {
                        &each.id
                    } else {
                        &each.journal_prefix
                    }
                })
                .collect();
            if values.iter().collect::<BTreeSet<_>>().len() != values.len() {
                return Err(RegistryError(format!(
                    "two capabilities share one {attribute}"
                )));
            }
        }
        let by_id = definitions
            .iter()
            .enumerate()
            .map(|(at, definition)| (definition.id.clone(), at))
            .collect();
        let registry = Registry { definitions, by_id };
        registry.check_requirements()?;
        Ok(registry)
    }

    /// `_check_requirements`: every required id is a capability of this registry, and the requirement graph has no cycle.
    fn check_requirements(&self) -> Result<(), RegistryError> {
        for definition in &self.definitions {
            for other in &definition.requires {
                if !self.by_id.contains_key(other) {
                    return Err(RegistryError(format!(
                        "{} requires an unknown capability {other}",
                        definition.id
                    )));
                }
            }
        }
        // 0 visiting, 1 done.
        let mut colour: HashMap<String, u8> = HashMap::new();
        fn visit(
            registry: &Registry,
            colour: &mut HashMap<String, u8>,
            capability: &str,
        ) -> Result<(), RegistryError> {
            match colour.get(capability) {
                Some(1) => return Ok(()),
                Some(0) => {
                    return Err(RegistryError(format!(
                        "the requirements of {capability} form a cycle"
                    )));
                }
                _ => {}
            }
            colour.insert(capability.to_owned(), 0);
            for other in &registry.definitions[registry.by_id[capability]].requires {
                visit(registry, colour, other)?;
            }
            colour.insert(capability.to_owned(), 1);
            Ok(())
        }
        for definition in &self.definitions {
            visit(self, &mut colour, &definition.id)?;
        }
        Ok(())
    }

    /// `requires(capability)`: the ids `capability` needs on, transitively, in a stable order (each required capability's own
    /// requirements before it); empty for one that needs none or is not of this registry.
    pub fn requires(&self, capability: &str) -> Vec<String> {
        let mut found: Vec<String> = Vec::new();
        let mut seen: BTreeSet<String> = BTreeSet::new();
        fn visit(
            registry: &Registry,
            current: &str,
            found: &mut Vec<String>,
            seen: &mut BTreeSet<String>,
        ) {
            let Some(definition) = registry.get(current) else {
                return;
            };
            for other in &definition.requires {
                if !seen.contains(other) {
                    seen.insert(other.clone());
                    visit(registry, other, found, seen);
                    found.push(other.clone());
                }
            }
        }
        visit(self, capability, &mut found, &mut seen);
        found
    }

    /// `required_by(capability)`: the ids that need `capability` on, transitively, in the registry's order.
    pub fn required_by(&self, capability: &str) -> Vec<String> {
        self.definitions
            .iter()
            .filter(|definition| {
                self.requires(&definition.id)
                    .iter()
                    .any(|other| other == capability)
            })
            .map(|definition| definition.id.clone())
            .collect()
    }

    /// `ids`.
    pub fn ids(&self) -> Vec<&str> {
        self.definitions
            .iter()
            .map(|each| each.id.as_str())
            .collect()
    }

    pub fn get(&self, capability: &str) -> Option<&CapabilityDef> {
        self.by_id.get(capability).map(|at| &self.definitions[*at])
    }

    /// `at(point)`: the capabilities whose code answers at `point`, in the registry's order. Never an action.
    pub fn at(&self, point: Point) -> Vec<&CapabilityDef> {
        self.definitions
            .iter()
            .filter(|definition| {
                definition.kind == CapabilityKind::Route && definition.answers_at(point)
            })
            .collect()
    }

    pub fn len(&self) -> usize {
        self.definitions.len()
    }

    pub fn is_empty(&self) -> bool {
        self.definitions.is_empty()
    }

    pub fn iter(&self) -> std::slice::Iter<'_, CapabilityDef> {
        self.definitions.iter()
    }
}

impl<'a> IntoIterator for &'a Registry {
    type Item = &'a CapabilityDef;
    type IntoIter = std::slice::Iter<'a, CapabilityDef>;

    fn into_iter(self) -> Self::IntoIter {
        self.definitions.iter()
    }
}

/// `DEFINITIONS`: what this edition ships, in the order they answer in.
pub fn definitions() -> Vec<CapabilityDef> {
    crate::registry_gen::definitions()
}

/// `WAITING`: the hidden capabilities, each with the measurements that must all pass first.
pub fn waiting() -> Vec<(CapabilityDef, Vec<Measurement>)> {
    crate::registry_gen::waiting()
}

/// `INSTALLED_ONLY`: what only an installation can have.
pub fn installed_only() -> Vec<CapabilityDef> {
    crate::registry_gen::installed_only()
}

/// `offered(measured)`: the waiting capabilities `measured` lets out: those whose measurements all passed (on whichever Codex).
pub fn offered(measured: &Table) -> Vec<CapabilityDef> {
    waiting()
        .into_iter()
        .filter(|(_definition, needs)| {
            needs.iter().all(|measurement| {
                measured
                    .get(measurement)
                    .is_some_and(|(verdict, _)| *verdict == Verdict::Pass)
            })
        })
        .map(|(definition, _needs)| definition)
        .collect()
}

/// `on_an_installation(root)`: the capabilities only an installation can have - where a bundled runtime stands beside
/// `app\src`. The host says whether it does (`installed`).
pub fn on_an_installation(installed: bool) -> Vec<CapabilityDef> {
    if installed {
        installed_only()
    } else {
        Vec::new()
    }
}

/// `_registry()`: the registry this edition runs - `DEFINITIONS`, what `measured` lets out, and the installation's own.
pub fn registry_for(measured: &Table, installed: bool) -> Result<Registry, RegistryError> {
    let mut all = definitions();
    all.extend(offered(measured));
    all.extend(on_an_installation(installed));
    Registry::new(all)
}

/// `REGISTRY`: the registry of the build-time table of measurements (`measured::table()`).
pub fn shipped(installed: bool) -> Result<Registry, RegistryError> {
    registry_for(&measured::table(), installed)
}

/// `shown(registry)`: the registry's capabilities in `SHOWN_ORDER`; any it does not name after them, in the registry's own order.
pub fn shown(registry: &Registry) -> Vec<&CapabilityDef> {
    let place: HashMap<&str, usize> = SHOWN_ORDER
        .iter()
        .enumerate()
        .map(|(at, id)| (*id, at))
        .collect();
    let mut ordered: Vec<(usize, usize, &CapabilityDef)> = registry
        .iter()
        .enumerate()
        .map(|(index, definition)| {
            (
                place
                    .get(definition.id.as_str())
                    .copied()
                    .unwrap_or(place.len()),
                index,
                definition,
            )
        })
        .collect();
    ordered.sort_by_key(|(at, index, _)| (*at, *index));
    ordered
        .into_iter()
        .map(|(_, _, definition)| definition)
        .collect()
}
