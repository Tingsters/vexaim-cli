//! Isolate a Windows connection-parameter hypothesis without changing releases.
use crate::repl::Fail;
use btleplug::api::{ConnectionParameterPreset, Peripheral};
use serde_json::{Value, json};
use std::time::Duration;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Profile {
    Throughput,
    OsDefault,
}

impl Profile {
    pub(crate) fn selected() -> Result<Self, Fail> {
        #[cfg(feature = "ble-diagnostics")]
        {
            return Self::parse(
                std::env::var("VEXAIM_DIAGNOSTIC_CONNECTION_PROFILE")
                    .ok()
                    .as_deref(),
            );
        }
        #[cfg(not(feature = "ble-diagnostics"))]
        Ok(Self::Throughput)
    }

    #[cfg(any(test, feature = "ble-diagnostics"))]
    fn parse(value: Option<&str>) -> Result<Self, Fail> {
        match value {
            None | Some("throughput") => Ok(Self::Throughput),
            Some("os-default") => Ok(Self::OsDefault),
            Some(_) => Err(Fail::Session(
                "Unknown diagnostic Bluetooth connection profile".into(),
            )),
        }
    }

    pub(crate) async fn apply<P: Peripheral>(&self, peripheral: &P) -> Value {
        let mut report = self
            .request(
                async {
                    peripheral
                        .request_connection_parameters(
                            ConnectionParameterPreset::ThroughputOptimized,
                        )
                        .await
                        .map_err(|e| e.to_string())
                },
                Duration::from_secs(3),
            )
            .await;
        report["actual"] =
            match tokio::time::timeout(Duration::from_secs(2), peripheral.connection_parameters())
                .await
            {
                Ok(Ok(Some(p))) => json!({"interval_us":p.interval_us,"latency":p.latency,
                "supervision_timeout_us":p.supervision_timeout_us}),
                _ => Value::Null,
            };
        report
    }

    async fn request<F>(&self, operation: F, budget: Duration) -> Value
    where
        F: std::future::Future<Output = Result<(), String>>,
    {
        match self {
            Self::OsDefault => json!({"requested":"os-default","accepted":null,"error":null}),
            Self::Throughput => match tokio::time::timeout(budget, operation).await {
                Ok(Ok(())) => json!({"requested":"throughput","accepted":true,"error":null}),
                Ok(Err(error)) => json!({"requested":"throughput","accepted":false,"error":error}),
                Err(_) => {
                    json!({"requested":"throughput","accepted":false,"error":"parameter request timed out"})
                }
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn diagnostic_profiles_are_explicit_and_do_not_change_the_release_default() {
        assert_eq!(Profile::parse(None).unwrap(), Profile::Throughput);
        assert_eq!(
            Profile::parse(Some("os-default")).unwrap(),
            Profile::OsDefault
        );
        assert!(Profile::parse(Some("typo")).is_err());
        #[cfg(not(feature = "ble-diagnostics"))]
        assert_eq!(Profile::selected().unwrap(), Profile::Throughput);
    }

    #[tokio::test]
    async fn os_default_never_polls_the_parameter_request() {
        let value = Profile::OsDefault
            .request(
                async { panic!("must not request parameters") },
                Duration::ZERO,
            )
            .await;
        assert!(value["accepted"].is_null());
    }

    #[tokio::test]
    async fn rejected_and_stalled_requests_are_observable() {
        let rejected = Profile::Throughput
            .request(
                async { Err("unsupported by adapter".into()) },
                Duration::from_secs(1),
            )
            .await;
        assert_eq!(rejected["accepted"], false);
        assert_eq!(rejected["error"], "unsupported by adapter");
        let timed = Profile::Throughput
            .request(std::future::pending(), Duration::from_millis(1))
            .await;
        assert_eq!(timed["accepted"], false);
        assert_eq!(timed["error"], "parameter request timed out");
    }
}
