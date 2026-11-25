//! Review 5: the float repr at a power of two (REVIEW-int5.md, finding on json/float.rs).
//!
//! At x = 2^k the doubles below x are twice as close as those above, so the interval that reads back as x is
//! narrower below it. For 46 powers of two (2^-24 = 5.960464477539063e-08 among them) the shortest length is
//! 16 or 17 digits, the nearest form of that length lies below x outside that interval, and Python's dtoa takes
//! the one above. `push_repr` (and car-brand's `pyfmt::repr`, the same rule) rounds x exactly to the length, so
//! it writes the one below: a text Python never writes and that does not read back as x (in a debug build the
//! `debug_assert_eq!` in float.rs panics instead). The expected texts are Python 3.13.15's `repr(x)`.

use car_machine::json::{Options, Value, to_string};

const PYTHON: &[(u64, &str)] = &[
    (0x0060000000000000, "7.120236347223045e-307"),
    (0x0100000000000000, "7.291122019556398e-304"),
    (0x0420000000000000, "8.209073602596753e-289"),
    (0x0660000000000000, "5.641232424577593e-278"),
    (0x0D70000000000000, "5.858190679279809e-244"),
    (0x0E80000000000000, "7.678447687145631e-239"),
    (0x0EB0000000000000, "6.142758149716505e-238"),
    (0x0F50000000000000, "6.290184345309701e-235"),
    (0x13E0000000000000, "5.940911144672375e-213"),
    (0x1480000000000000, "6.083493012144512e-210"),
    (0x1690000000000000, "5.225680706521042e-200"),
    (0x1730000000000000, "5.351097043477547e-197"),
    (0x1DA0000000000000, "5.426657103235053e-166"),
    (0x2020000000000000, "5.966672584960166e-154"),
    (0x20F0000000000000, "4.887898181599368e-150"),
    (0x2160000000000000, "6.256509672447191e-148"),
    (0x2800000000000000, "5.075883674631299e-116"),
    (0x2910000000000000, "6.653062250012736e-111"),
    (0x2D70000000000000, "7.854549544476363e-90"),
    (0x3730000000000000, "7.174648137343064e-43"),
    (0x39E0000000000000, "6.310887241768095e-30"),
    (0x3B20000000000000, "6.617444900424222e-24"),
    (0x3D30000000000000, "5.684341886080802e-14"),
    (0x3E70000000000000, "5.960464477539063e-08"),
    (0x4580000000000000, "6.189700196426902e+26"),
    (0x4790000000000000, "5.316911983139664e+36"),
    (0x4830000000000000, "5.444517870735016e+39"),
    (0x4AB0000000000000, "5.986310706507379e+51"),
    (0x4B50000000000000, "6.129982163463556e+54"),
    (0x5120000000000000, "6.070840288205404e+82"),
    (0x5300000000000000, "6.518515124270356e+91"),
    (0x5580000000000000, "7.167183174968974e+103"),
    (0x5790000000000000, "6.156563468186638e+113"),
    (0x58D0000000000000, "6.455624695217272e+119"),
    (0x5940000000000000, "8.263199609878108e+121"),
    (0x5E00000000000000, "6.243497100631985e+144"),
    (0x6150000000000000, "5.623642243178996e+160"),
    (0x61F0000000000000, "5.758609657015292e+163"),
    (0x6290000000000000, "5.896816288783659e+166"),
    (0x63D0000000000000, "6.183260036827614e+172"),
    (0x6510000000000000, "6.483618076376552e+178"),
    (0x6C50000000000000, "5.386379163185535e+213"),
    (0x7220000000000000, "5.334411546303884e+241"),
    (0x75E0000000000000, "6.150157786156811e+259"),
    (0x77F0000000000000, "5.282945311356653e+269"),
    (0x7CF0000000000000, "6.386688990511104e+293"),
];

fn written(x: f64) -> String {
    std::panic::catch_unwind(|| to_string(&Value::Float(x), &Options::new()).unwrap())
        .unwrap_or_else(|_| "<panicked>".to_owned())
}

#[test]
fn a_power_of_two_is_written_as_python_writes_it() {
    let differs: Vec<String> = PYTHON
        .iter()
        .filter_map(|(bits, want)| {
            let got = written(f64::from_bits(*bits));
            (got != *want).then(|| format!("{want} written as {got}"))
        })
        .collect();
    assert!(
        differs.is_empty(),
        "{} of {} differ: {:?}",
        differs.len(),
        PYTHON.len(),
        differs
    );
}

#[test]
fn the_written_text_reads_back_as_the_float() {
    for (bits, _) in PYTHON {
        let x = f64::from_bits(*bits);
        let got = written(x);
        assert_eq!(
            got.parse::<f64>().ok(),
            Some(x),
            "{got} does not read back as {x:e}"
        );
    }
}
