//! Small, reusable robot-side actions. Students use prompts; these are agent tools.
use crate::repl::Fail;
use clap::ValueEnum;

pub const HELPERS: &str = include_str!("motion.py");
#[cfg(feature = "bluetooth")]
pub const EVENT_PREFIX: &str = "__VEXAIM_EVENT__";

#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum Direction {
    Left,
    Right,
}

fn number(value: f64, min: f64, max: f64, name: &str) -> Result<(), Fail> {
    if !value.is_finite() || !(min..=max).contains(&value) {
        return Err(Fail::Io(format!(
            "{name} must be finite and between {min} and {max}; no motion sent"
        )));
    }
    Ok(())
}

pub fn turn_source(direction: Direction, degrees: f64, speed: f64) -> Result<String, Fail> {
    number(degrees, 0.1, 360.0, "turn degrees")?;
    number(speed, 30.0, 90.0, "turn speed (DPS)")?;
    let signed = if matches!(direction, Direction::Left) {
        -degrees
    } else {
        degrees
    };
    Ok(format!("_va_motion('turn', {signed}, 0, {speed})\n"))
}

pub fn move_source(distance: f64, angle: f64, speed: f64) -> Result<String, Fail> {
    number(distance, 0.1, 500.0, "distance (mm)")?;
    number(angle, -360.0, 360.0, "movement angle")?;
    number(speed, 40.0, 100.0, "movement speed (mm/s)")?;
    Ok(format!(
        "_va_motion('move', {distance}, {angle}, {speed})\n"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_non_finite_and_unbounded_motion_before_transmission() {
        for n in [f64::NAN, f64::INFINITY, -1.0, 0.0, 361.0] {
            assert!(turn_source(Direction::Left, n, 30.0).is_err());
        }
        assert!(turn_source(Direction::Left, 360.0, 91.0).is_err());
        assert!(move_source(501.0, 0.0, 80.0).is_err());
        assert!(move_source(100.0, f64::NAN, 80.0).is_err());
        assert!(move_source(500.0, 0.0, 39.0).is_err());
        assert!(
            turn_source(Direction::Left, 360.0, 60.0)
                .unwrap()
                .contains("-360")
        );
        assert!(
            turn_source(Direction::Right, 360.0, 90.0)
                .unwrap()
                .contains(" 360")
        );
    }
}
