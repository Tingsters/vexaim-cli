//! One catalogue drives validation, runtime dispatch and agent discovery.
use crate::repl::Fail;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;

pub const RUNTIME: &str = include_str!("device.py");
pub const BEHAVIORS: &str = include_str!("behaviors.py");

pub fn needs_behaviors(action: &Action) -> bool {
    action.kind == "macro"
        && matches!(
            action.args.first().and_then(Value::as_str),
            Some("collect" | "approach" | "search-left" | "search-right")
        )
}

pub fn behavior_exec(source: &str, timeout: u64) -> String {
    // The matching runtime is cached by the session owner. User text stays data.
    format!(
        "_vx_behavior_exec({}, {})\n",
        serde_json::to_string(source).unwrap(),
        timeout * 1000
    )
}
// Result pacing is outside the robot action deadline (16 KiB at 128 B/100 ms).
// Include helper upload and final cleanup when used without a persistent owner.
pub const RESULT_TIMEOUT_SECS: u64 = 25;
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Action {
    pub command: String,
    pub method: String,
    pub kind: String,
    pub args: Vec<Value>,
    pub timeout: u64,
    pub duration_ms: Option<u64>,
    pub no_wait: bool,
    pub velocity: Option<f64>,
    pub velocity_units: Option<String>,
    pub sample_ms: Option<u64>,
    pub experimental: bool,
}
pub fn fail(s: impl ToString) -> Fail {
    Fail::Io(s.to_string())
}
pub fn jsonl_records(mut value: Value) -> Vec<Value> {
    fn extract(value: &mut Value, records: &mut Vec<Value>) {
        if let Some(object) = value.as_object_mut() {
            for (field, event) in [("samples", "sample"), ("events", "callback")] {
                if let Some(Value::Array(items)) = object.remove(field) {
                    let count = items.len();
                    for item in items {
                        let mut record = if item.is_object() {
                            item
                        } else {
                            json!({"value":item})
                        };
                        record["event"] = json!(event);
                        records.push(record);
                    }
                    object.insert(format!("{field}_count"), json!(count));
                }
            }
            for key in ["value", "action"] {
                if let Some(nested) = object.get_mut(key) {
                    extract(nested, records);
                }
            }
        }
    }
    let mut records = Vec::new();
    extract(&mut value, &mut records);
    value["event"] = json!("result");
    records.push(value);
    records
}
pub fn print_jsonl(value: Value) {
    for record in jsonl_records(value) {
        println!("{record}");
    }
}
fn specs() -> impl Iterator<Item = Vec<&'static str>> {
    include_str!("catalog.tsv")
        .lines()
        .filter(|s| !s.starts_with('#') && !s.is_empty())
        .map(|s| s.split('|').collect())
}
pub fn catalog(group: Option<&str>) -> Value {
    let commands: Vec<_> = specs().filter(|s|group.is_none_or(|g|s[0].starts_with(&format!("{g} ")))).map(|s|json!({"command":s[0],"python":s[1],"kind":s[2],"parameters":s[3],"options":["--timeout 1..120","--emit-python","--no-wait (session)","--duration 2s (continuous/events)","--sample-ms 100 (read)","--units mm|cm|m (distance)","--velocity N --velocity-units mmps|dps|percent"],"availability":"requires live capability check; API presence does not prove hardware behavior"})).collect();
    json!({"schema_version":1,"model":"VEX AIM","commands":commands,"host_commands":["catalog [group]","capabilities --live","camera observe --output-dir DIR [--with-detections] [--camera-index N]","snap -o FILE","session start|status|close","doctor","info","exec","stop"],"unsupported":["firmware updates","saved program management","raw encoders","microphone recording","custom neural model training","Wi-Fi transport"],"sources":["https://api.vex.com/aim/home/python/","https://github.com/VEX-Robotics/vex-vsc-extension"]})
}
pub fn capability_source() -> String {
    let paths: Vec<_> = specs()
        .map(|s| s[1].to_owned())
        .filter(|s| !s.starts_with('_') && !s.starts_with("host."))
        .collect();
    format!(
        "{}\n_vx_print(_vx_capabilities({}))\n",
        RUNTIME,
        python_json(&json!(paths))
    )
}
pub fn python_json(value: &Value) -> String {
    // Decode JSON inside Python, never interpolate user text as executable code.
    format!(
        "_vx_json.loads({})",
        serde_json::to_string(&value.to_string()).unwrap()
    )
}
#[cfg(test)]
pub fn source(a: &Action) -> String {
    format!(
        "{RUNTIME}\n{}\n_vx_print(_vx_dispatch({}))\n",
        if needs_behaviors(a) { BEHAVIORS } else { "" },
        python_json(&serde_json::to_value(a).unwrap())
    )
}
pub fn standalone(a: &Action) -> String {
    format!(
        "{RUNTIME}\n{}\n_vx_result = _vx_dispatch({})\nif 'action' in _vx_result:\n    _vx_print(_vx_action_wait(_vx_result['action']['id'], {}))\nelse:\n    _vx_print(_vx_result)\n",
        if needs_behaviors(a) { BEHAVIORS } else { "" },
        python_json(&serde_json::to_value(a).unwrap()),
        (a.timeout + 2) * 1000
    )
}
fn value(raw: &str, ty: &str) -> Result<Value, Fail> {
    let upper = raw.to_uppercase().replace('-', "_");
    if ty == "optional-number" && raw == "null" {
        return Ok(Value::Null);
    }
    if let Some(choices) = ty.strip_prefix("enum(").and_then(|s| s.strip_suffix(')')) {
        if choices.split(',').any(|s| s == upper) {
            return Ok(json!({"constant":upper}));
        }
        return Err(fail(format!("Expected one of {choices}, got {raw}")));
    }
    let constant = |name: String| Ok(json!({"constant":name}));
    match ty {
        "text" => {
            if raw.len() > 512 {
                return Err(fail("Text is limited to 512 UTF-8 bytes"));
            }
            Ok(json!(raw))
        }
        "json" => {
            let v: Value = serde_json::from_str(raw).map_err(fail)?;
            if !v.is_array() || raw.len() > 512 {
                return Err(fail("Data must be a JSON array, at most 512 bytes"));
            }
            Ok(v)
        }
        "bool" => match raw {
            "true" | "on" => Ok(json!(true)),
            "false" | "off" => Ok(json!(false)),
            _ => Err(fail("Expected true or false")),
        },
        "target" => {
            if [
                "ALL_AIOBJS",
                "ALL_TAGS",
                "ALL_COLORS",
                "ALL_CODES",
                "SPORTS_BALL",
                "ORANGE_BARREL",
                "BLUE_BARREL",
                "AIM_ROBOT",
            ]
            .contains(&upper.as_str())
            {
                return constant(upper);
            }
            let (prefix, n) = upper.split_once(':').ok_or_else(|| {
                fail("Target must be a VEX class, tag:N, color:1..7 or code:1..8")
            })?;
            let n: u32 = n.parse().map_err(fail)?;
            if !matches!(prefix, "TAG" | "COLOR" | "CODE")
                || (prefix == "COLOR" && !(1..=7).contains(&n))
                || (prefix == "CODE" && !(1..=8).contains(&n))
                || n > 255
            {
                return Err(fail("Invalid target ID"));
            }
            Ok(json!({"target":prefix,"id":n}))
        }
        "leds" => {
            if upper == "ALL" || upper == "ALL_LEDS" {
                return constant("ALL_LEDS".into());
            }
            let values: Result<Vec<_>, _> = upper
                .split(',')
                .map(|s| {
                    let n = s
                        .strip_prefix("LED")
                        .unwrap_or(s)
                        .parse::<u32>()
                        .map_err(fail)?;
                    if !(1..=6).contains(&n) {
                        return Err(fail("LEDs are numbered 1..6"));
                    }
                    Ok(json!({"constant":format!("LED{n}")}))
                })
                .collect();
            let mut values = values?;
            if values.len() == 1 {
                Ok(values.remove(0))
            } else {
                Ok(json!(values))
            }
        }
        "color" => {
            if raw.starts_with('#')
                && raw.len() == 7
                && raw[1..].chars().all(|c| c.is_ascii_hexdigit())
            {
                return Ok(json!({"color":raw}));
            }
            if raw.contains(',') {
                let rgb: Result<Vec<_>, _> = raw.split(',').map(|s| s.parse::<u8>()).collect();
                let rgb = rgb.map_err(fail)?;
                if rgb.len() == 3 {
                    return Ok(json!({"rgb":rgb}));
                }
            }
            if [
                "BLACK",
                "WHITE",
                "RED",
                "GREEN",
                "BLUE",
                "YELLOW",
                "ORANGE",
                "PURPLE",
                "CYAN",
                "TRANSPARENT",
            ]
            .contains(&upper.as_str())
            {
                return constant(upper);
            }
            Err(fail("Color must be a VEX color, #RRGGBB, or R,G,B"))
        }
        "image-slot" | "sound-slot" => {
            let n: u8 = raw
                .trim_start_matches("IMAGE")
                .trim_start_matches("SOUND")
                .parse()
                .map_err(fail)?;
            if !(1..=10).contains(&n) {
                return Err(fail("Asset slots are 1..10"));
            }
            constant(format!(
                "{}{n}",
                if ty == "image-slot" { "IMAGE" } else { "SOUND" }
            ))
        }
        "sound" => {
            if !"ACT_ANGRY ACT_EXCITED ACT_HAPPY ACT_SAD ACT_SILLY BLINKER BRAKES CHEER CHIRP COMPLETE CRASH DETECTED DOORBELL FAIL FLOURISH HUAH LOOPING MOVE_FORWARD MOVE_REVERSE OBSTACLE PAUSE PICKUP RECEIVE RESUME SENSING SEND SPARKLE TADA TURN_LEFT TURN_RIGHT".split_whitespace().any(|s|s==upper) {return Err(fail("Unknown AIM sound; see catalog"));}
            constant(upper)
        }
        "emoji" => {
            if !"EXCITED CONFIDENT SILLY AMAZED STRONG THRILLED HAPPY PROUD LAUGHING OPTIMISTIC DETERMINED AFFECTIONATE CALM QUIET SHY CHEERFUL LOVED SURPRISED THINKING TIRED CONFUSED BORED EMBARRASSED WORRIED SAD SICK DISAPPOINTED NERVOUS ANNOYED STRESSED ANGRY FRUSTRATED JEALOUS SHOCKED FEAR DISGUST".split_whitespace().any(|s|s==upper) {return Err(fail("Unknown AIM emoji"));}
            constant(upper)
        }
        "note" => {
            let bytes = upper.as_bytes();
            if !(bytes.len() == 2 || bytes.len() == 3)
                || !(b'A'..=b'G').contains(&bytes[0])
                || !(b'5'..=b'8').contains(bytes.last().unwrap())
                || (bytes.len() == 3 && bytes[1] != b'#')
            {
                return Err(fail("Note must be A..G, optional #, octave 5..8"));
            }
            Ok(json!(upper))
        }
        "colors" => {
            let nums: Result<Vec<u8>, _> = raw.split(',').map(str::parse).collect();
            let nums = nums.map_err(fail)?;
            if !(2..=4).contains(&nums.len()) || nums.iter().any(|n| !(1..=7).contains(n)) {
                return Err(fail("Code needs 2..4 color indices, each 1..7"));
            }
            Ok(json!(nums))
        }
        "event" => {
            if ![
                "screen.pressed",
                "screen.released",
                "timer.event",
                "inertial.changed",
                "inertial.collision",
                "inertial.crashed",
                "inertial.shake",
                "link.connected",
                "link.disconnected",
                "link.handle_message",
                "controller.axis1.changed",
                "controller.axis2.changed",
                "controller.button_up.pressed",
                "controller.button_up.released",
                "controller.button_down.pressed",
                "controller.button_down.released",
                "controller.button_left.pressed",
                "controller.button_left.released",
                "controller.button_right.pressed",
                "controller.button_right.released",
                "controller.button_stick.pressed",
                "controller.button_stick.released",
            ]
            .contains(&raw)
            {
                return Err(fail("Unsupported event source"));
            }
            Ok(json!(raw))
        }
        _ => {
            let n: f64 = raw.parse().map_err(fail)?;
            let (min, max, integer) = match ty {
                "positive" => (0.000001, 1e9, false),
                "heading" => (0., 359.999999, false),
                "vector" => (-100., 100., false),
                "percent" => (0., 100., true),
                "move-speed" => (0.1, 200., false),
                "turn-speed" => (0.1, 150., false),
                "byte" => (0., 255., true),
                "count" => (1., 24., true),
                "color-index" => (1., 7., true),
                "code-index" => (1., 8., true),
                "hue" => (1., 40., false),
                "saturation" => (0.1, 1., false),
                "milliseconds" => (1., 120000., true),
                "integer" => (0., 255., true),
                _ => (-1e9, 1e9, false),
            };
            if !n.is_finite() || !(min..=max).contains(&n) || (integer && n.fract() != 0.) {
                return Err(fail(format!(
                    "{ty} must be finite in {min}..{max}{}",
                    if integer { " and integral" } else { "" }
                )));
            }
            Ok(if integer { json!(n as i64) } else { json!(n) })
        }
    }
}
pub fn parse(words: &[String], session: bool) -> Result<Action, Fail> {
    let mut words = words.to_vec();
    if let Some(first) = words.first().map(String::as_str) {
        let (angle, distance_index) = match first {
            "forward" => (0, 1),
            "back" | "backward" => (180, 1),
            "strafe" => {
                if words.len() < 3 {
                    return Err(fail("strafe left|right DISTANCE"));
                }
                (
                    match words[1].as_str() {
                        "left" => 270,
                        "right" => 90,
                        _ => return Err(fail("strafe left|right DISTANCE")),
                    },
                    2,
                )
            }
            _ => (-1, 0),
        };
        if angle >= 0 {
            if words.len() <= distance_index {
                return Err(fail("Give a distance"));
            }
            let mut tail = words.split_off(distance_index + 1);
            words = vec![
                "motion".into(),
                "move-for".into(),
                words[distance_index].clone(),
                angle.to_string(),
            ];
            words.append(&mut tail);
        }
    }
    if words.len() < 2 {
        return Err(fail("Use catalog GROUP to list commands and arguments"));
    }
    let key = format!("{} {}", words[0], words[1]);
    let spec = specs()
        .find(|s| s[0] == key)
        .ok_or_else(|| fail(format!("Unknown AIM command {key}; see catalog")))?;
    let mut options = BTreeMap::<String, String>::new();
    let mut positional = Vec::new();
    let mut i = 2;
    while i < words.len() {
        if words[i].starts_with("--") {
            let name = words[i].trim_start_matches("--");
            if ["no-wait", "experimental", "emit-python"].contains(&name) {
                if options.insert(name.into(), "true".into()).is_some() {
                    return Err(fail("Duplicate option"));
                }
            } else {
                i += 1;
                if i >= words.len() {
                    return Err(fail(format!("Missing value for --{name}")));
                }
                if options.insert(name.into(), words[i].clone()).is_some() {
                    return Err(fail("Duplicate option"));
                }
            }
        } else {
            positional.push(words[i].clone());
        }
        i += 1;
    }
    for name in options.keys() {
        if ![
            "timeout",
            "duration",
            "no-wait",
            "velocity",
            "velocity-units",
            "units",
            "sample-ms",
            "experimental",
            "emit-python",
        ]
        .contains(&name.as_str())
        {
            return Err(fail(format!("Unknown option --{name}")));
        }
    }
    let params: Vec<_> = spec[3].split_whitespace().collect();
    if positional.len() > params.len() {
        return Err(fail(format!("Expected: {key} {}", spec[3])));
    }
    let mut args = Vec::new();
    for (i, param) in params.iter().enumerate() {
        let (name, ty) = param.split_once(':').unwrap();
        let (ty, default) = ty.split_once('=').map_or((ty, None), |(a, b)| (a, Some(b)));
        let raw = positional
            .get(i)
            .map(String::as_str)
            .or(default)
            .ok_or_else(|| fail(format!("Missing {name}; expected {key} {}", spec[3])))?;
        args.push(value(raw, ty)?);
    }
    if let Some(units) = options.get("units") {
        if key != "motion move-for" {
            return Err(fail("--units is only for distances"));
        }
        let scale = match units.as_str() {
            "mm" => 1.,
            "cm" => 10.,
            "m" => 1000.,
            _ => return Err(fail("Distance units: mm, cm, m")),
        };
        let mm = args[0].as_f64().unwrap() * scale;
        args[0] = value(&mm.to_string(), "positive")?;
    }
    let timeout: u64 = options
        .get("timeout")
        .map(String::as_str)
        .unwrap_or("30")
        .parse()
        .map_err(fail)?;
    if !(1..=120).contains(&timeout) {
        return Err(fail("Timeout is 1..120 seconds"));
    }
    let duration_ms = options
        .get("duration")
        .map(|s| {
            let (raw, scale) = if let Some(v) = s.strip_suffix("ms") {
                (v, 1.)
            } else if let Some(v) = s.strip_suffix('s') {
                (v, 1000.)
            } else {
                (s.as_str(), 1000.)
            };
            let n: f64 = raw.parse().map_err(fail)?;
            if !n.is_finite() || n < 1. / scale || n * scale > timeout as f64 * 1000. {
                return Err(fail("Duration must be positive and within timeout"));
            }
            Ok((n * scale) as u64)
        })
        .transpose()?;
    if matches!(spec[2], "continuous" | "experimental" | "events") && duration_ms.is_none() {
        return Err(fail("This operation requires --duration (for example 2s)"));
    }
    if duration_ms.is_some()
        && !matches!(spec[2], "continuous" | "experimental" | "events" | "read")
    {
        return Err(fail(
            "--duration is for continuous motion, events or sampled reads; finite actions use --timeout",
        ));
    }
    let no_wait = options.contains_key("no-wait");
    if spec[2] == "host" && !options.is_empty() {
        return Err(fail(
            "LCD screenshots use a fixed 60-second capture deadline and a positional .png output; native action options do not apply",
        ));
    }
    if no_wait && !session {
        return Err(fail("--no-wait requires an owned --session"));
    }
    if spec[2] == "experimental" && !options.contains_key("experimental") {
        return Err(fail(
            "Independent wheel signs/units need hardware validation; opt in with --experimental",
        ));
    }
    if options.contains_key("experimental") && spec[2] != "experimental" {
        return Err(fail(
            "--experimental only applies to independent wheel control",
        ));
    }
    let velocity = options
        .get("velocity")
        .map(|s| s.parse::<f64>().map_err(fail))
        .transpose()?;
    let velocity_units = options.get("velocity-units").map(|s| s.to_uppercase());
    if velocity.is_some() || velocity_units.is_some() {
        if !matches!(spec[2], "motion" | "continuous") || key.ends_with("move-with-vectors") {
            return Err(fail(
                "Velocity is only valid for native move/turn operations",
            ));
        }
        let units = velocity_units
            .as_deref()
            .ok_or_else(|| fail("Explicit velocity needs --velocity-units"))?;
        let turn = key.contains("turn");
        let max = match (turn, units) {
            (true, "DPS") => 150.,
            (false, "MMPS") => 200.,
            (_, "PERCENT") => 100.,
            _ => return Err(fail("Move units: mmps/percent; turn units: dps/percent")),
        };
        let v = velocity.ok_or_else(|| fail("Give --velocity"))?;
        if !v.is_finite() || v <= 0. || v > max {
            return Err(fail(format!("Velocity must be in 0..{max}")));
        }
    }
    if matches!(spec[2], "setting") && key.starts_with("motion set-") {
        if args[1]["constant"] == "PERCENT" && args[0].as_f64().unwrap() > 100. {
            return Err(fail("Percent velocity cannot exceed 100"));
        }
    }
    let sample_ms = options
        .get("sample-ms")
        .map(|s| s.parse::<u64>().map_err(fail))
        .transpose()?
        .or(if spec[2] == "read" && duration_ms.is_some() {
            Some(100)
        } else {
            None
        });
    if let Some(ms) = sample_ms {
        if !(50..=60000).contains(&ms) || spec[2] != "read" || duration_ms.is_none() {
            return Err(fail(
                "Sampling requires a read operation, --duration, and --sample-ms 50..60000",
            ));
        }
        if duration_ms.unwrap().div_ceil(ms) > 256 {
            return Err(fail(
                "Sampling exceeds 256 records; shorten duration or increase --sample-ms",
            ));
        }
    }
    Ok(Action {
        command: key,
        method: spec[1].into(),
        kind: spec[2].into(),
        args,
        timeout,
        duration_ms,
        no_wait,
        velocity,
        velocity_units,
        sample_ms,
        experimental: options.contains_key("experimental"),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn parse(s: &str) -> Result<Action, Fail> {
        super::parse(
            &s.split_whitespace().map(str::to_owned).collect::<Vec<_>>(),
            true,
        )
    }
    #[test]
    fn metric_and_holonomic() {
        let a = parse("strafe left 0.2 --units m").unwrap();
        assert_eq!(a.args, json!([200.0, 270.0]).as_array().unwrap().clone());
        assert!(parse("motion move-with-vectors 0 25 -20 --duration 2s --no-wait").is_ok());
        assert_eq!(parse("motion turn-for left 360").unwrap().args[1], 360.);
    }
    #[test]
    fn standalone_loads_vision_helpers_only_for_vision_macros() {
        // Ordinary effects must not pay the vision controller upload cost.
        for command in ["led on all BLUE", "macro act-happy"] {
            let action = parse(command).unwrap();
            assert!(!standalone(&action).contains("class _VxBehaviors:"));
        }
        for command in ["macro get-blue-barrel", "macro turn-right-until-blue-barrel"] {
            let action = parse(command).unwrap();
            assert!(standalone(&action).contains("class _VxBehaviors:"));
        }
    }
    #[test]
    fn invalid_never_transmits() {
        for s in [
            "forward NaN",
            "forward inf",
            "forward -1",
            "motion turn-for right 10 --velocity 151 --velocity-units dps",
            "motion move-at 90",
            "motion move-with-vectors 0 101 0 --duration 2s",
            "motion move-for 4 --units feet",
            "led on 7 RED",
            "sound play-note C9 100",
            "screen print hello --bogus 2",
        ] {
            assert!(parse(s).is_err(), "{s}");
        }
    }
    #[test]
    fn every_spec_has_unique_command() {
        let mut seen = std::collections::HashSet::new();
        for s in specs() {
            assert_eq!(s.len(), 4);
            assert!(seen.insert(s[0]));
        }
    }
    #[test]
    fn injection_is_json_data() {
        let a = super::parse(
            &[
                "screen".into(),
                "print".into(),
                "\"; robot.turn(RIGHT) #".into(),
            ],
            true,
        )
        .unwrap();
        assert!(source(&a).contains("_vx_json.loads("));
    }
    #[test]
    fn duration_and_sampling_options_cannot_be_silently_ignored() {
        assert!(parse("led on all BLUE --duration 2s").is_err());
        assert!(parse("motion turn-for right 10 --duration 1s").is_err());
        assert!(parse("inertial get-heading --duration 30s").is_err());
        assert_eq!(
            parse("inertial get-heading --duration 2s")
                .unwrap()
                .sample_ms,
            Some(100)
        );
        assert_eq!(
            parse("inertial get-heading --duration 30s --sample-ms 200")
                .unwrap()
                .sample_ms,
            Some(200)
        );
    }
    #[test]
    fn jsonl_samples_are_separate_and_not_repeated_in_result() {
        let records = jsonl_records(
            json!({"ok":true,"action":{"id":"action-1","value":{"samples":[{"value":1},{"value":2}]}}}),
        );
        assert_eq!(records.len(), 3);
        assert_eq!(records[0]["event"], "sample");
        assert_eq!(records[2]["event"], "result");
        assert_eq!(records[2]["action"]["value"]["samples_count"], 2);
        assert!(records[2]["action"]["value"].get("samples").is_none());
    }
}
