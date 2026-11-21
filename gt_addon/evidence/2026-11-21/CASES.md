# Полный список 174 автоматических проверок

Список извлечён из JUnit успешного прогона; параметры считаются отдельными случаями.


## tests.test_atmosphere_inputs

- `test_history_and_provenance` — PASS.
- `test_bad_history_fails_without_bundle[<lambda>0]` — PASS.
- `test_bad_history_fails_without_bundle[<lambda>1]` — PASS.
- `test_bad_history_fails_without_bundle[<lambda>2]` — PASS.
- `test_bad_history_fails_without_bundle[<lambda>3]` — PASS.
- `test_bad_history_fails_without_bundle[<lambda>4]` — PASS.
- `test_worker_failure_cleans_staging` — PASS.
- `test_corrupt_array[<lambda>0]` — PASS.
- `test_corrupt_array[<lambda>1]` — PASS.
- `test_corrupt_array[<lambda>2]` — PASS.
- `test_reordered_csv_rejected` — PASS.
- `test_preparation_does_not_change_parent_source` — PASS.

## tests.test_celestrak_transport

- `test_stable_ranges_and_if_range` — PASS.
- `test_reject_inconsistent_range[etag]` — PASS.
- `test_reject_inconsistent_range[total]` — PASS.
- `test_reject_inconsistent_range[offset]` — PASS.
- `test_reject_inconsistent_range[end]` — PASS.
- `test_reject_inconsistent_range[weak]` — PASS.
- `test_reject_inconsistent_range[missing_tag]` — PASS.
- `test_reject_inconsistent_range[length]` — PASS.
- `test_reject_inconsistent_range[short]` — PASS.
- `test_reject_inconsistent_range[status200]` — PASS.
- `test_reject_inconsistent_range[encoding]` — PASS.
- `test_size_limit_before_accepting_chunk` — PASS.
- `test_server_ignores_first_range_but_complete_file_is_valid` — PASS.
- `test_retry_does_not_duplicate_committed_chunk` — PASS.
- `test_404_and_long_retry_after_not_hammered` — PASS.
- `test_conservative_source_choice[2024-01-01-auto-recent]` — PASS.
- `test_conservative_source_choice[2022-01-04-auto-recent]` — PASS.
- `test_conservative_source_choice[2022-01-03-auto-all]` — PASS.
- `test_conservative_source_choice[1960-01-01-auto-all]` — PASS.
- `test_conservative_source_choice[2024-01-01-all-all]` — PASS.
- `test_conservative_source_choice[2020-01-01-recent-recent]` — PASS.
- `test_invalid_dataset_before_download` — PASS.
- `test_cache_expiry_and_future_timestamp` — PASS.
- `test_cache_corruption_is_not_silently_used` — PASS.
- `test_cache_hit_has_original_timestamp_and_no_network` — PASS.
- `test_cache_write_failure_not_reported_as_success` — PASS.
- `test_real_http_range_round_trip` — PASS.

## tests.test_extended_contract

- `test_unicode_spaces_output_and_roundtrip[89]` — PASS.
- `test_unicode_spaces_output_and_roundtrip[96]` — PASS.
- `test_unicode_spaces_output_and_roundtrip[15B]` — PASS.
- `test_unicode_spaces_output_and_roundtrip[nrlmsis]` — PASS.
- `test_final_rename_failure_preserves_old_bundle[89]` — PASS.
- `test_final_rename_failure_preserves_old_bundle[96]` — PASS.
- `test_final_rename_failure_preserves_old_bundle[15B]` — PASS.
- `test_final_rename_failure_preserves_old_bundle[nrlmsis]` — PASS.
- `test_omni_leap_day_and_exclusive_end[2024-02-29-60]` — PASS.
- `test_omni_leap_day_and_exclusive_end[2024-03-01-61]` — PASS.
- `test_ta15_year_boundary_with_timezone` — PASS.
- `test_permanent_http_failure_not_retried[401]` — PASS.
- `test_permanent_http_failure_not_retried[403]` — PASS.
- `test_permanent_http_failure_not_retried[404]` — PASS.
- `test_permanent_http_failure_not_retried[410]` — PASS.
- `test_short_retry_after_respected` — PASS.
- `test_full_response_truncation_or_oversize_rejected[bad-4-20]` — PASS.
- `test_full_response_truncation_or_oversize_rejected[too large-9-4]` — PASS.
- `test_concurrent_cache_publish_never_mixes_body_and_metadata` — PASS.
- `test_cache_url_isolation` — PASS.
- `test_expired_cache_does_not_hide_network_failure` — PASS.
- `test_broken_cache_never_accepted[missing_body]` — PASS.
- `test_broken_cache_never_accepted[invalid_json]` — PASS.
- `test_broken_cache_never_accepted[path_digest]` — PASS.
- `test_atmosphere_bom_reversed_days_and_timezone` — PASS.
- `test_atmosphere_required_days_not_invented[duplicate]` — PASS.
- `test_atmosphere_required_days_not_invented[missing_first_history]` — PASS.
- `test_atmosphere_required_days_not_invented[missing_previous_day]` — PASS.
- `test_worker_success_with_wrong_interval_is_rejected[shifted]` — PASS.
- `test_worker_success_with_wrong_interval_is_rejected[short]` — PASS.
- `test_worker_success_with_wrong_interval_is_rejected[long]` — PASS.

## tests.test_input_data

- `test_values_provenance_and_repeated_calls` — PASS.
- `test_kp_bins[0-1]` — PASS.
- `test_kp_bins[3-1]` — PASS.
- `test_kp_bins[7-2]` — PASS.
- `test_kp_bins[13-2]` — PASS.
- `test_kp_bins[17-3]` — PASS.
- `test_kp_bins[53-6]` — PASS.
- `test_kp_bins[57-7]` — PASS.
- `test_kp_bins[90-7]` — PASS.
- `test_bad_data_no_output[<html>failure</html>]` — PASS.
- `test_bad_data_no_output[]` — PASS.
- `test_bad_data_no_output[body2]` — PASS.
- `test_bad_data_no_output[body3]` — PASS.
- `test_bad_data_no_output[body4]` — PASS.
- `test_bad_data_no_output[body5]` — PASS.
- `test_bad_data_no_output[body6]` — PASS.
- `test_bad_data_no_output[body7]` — PASS.
- `test_bad_data_no_output[body8]` — PASS.
- `test_bad_data_no_output[body9]` — PASS.
- `test_model_specific_missing` — PASS.
- `test_invalid_options_before_network[args0]` — PASS.
- `test_invalid_options_before_network[args1]` — PASS.
- `test_invalid_options_before_network[args2]` — PASS.
- `test_invalid_options_before_network[args3]` — PASS.
- `test_invalid_options_before_network[args4]` — PASS.
- `test_cross_year_and_timezone` — PASS.
- `test_retry_and_404` — PASS.
- `test_partial_write_cleanup` — PASS.
- `test_loading_corrupt_inputs[gap]` — PASS.
- `test_loading_corrupt_inputs[nan]` — PASS.
- `test_loading_corrupt_inputs[shape]` — PASS.
- `test_loading_corrupt_inputs[fill]` — PASS.
- `test_bad_interval_never_downloads[2024-01-01T00:01-2024-01-02]` — PASS.
- `test_bad_interval_never_downloads[2024-01-02-2024-01-01]` — PASS.
- `test_bad_interval_never_downloads[1962-01-01-1962-01-02]` — PASS.
- `test_bad_interval_never_downloads[2024-01-01-2026-01-01]` — PASS.
- `test_bad_interval_never_downloads[nonsense-2024-01-02]` — PASS.
- `test_bad_interval_never_downloads[2024-01-01-2024-01-01]` — PASS.
- `test_timeout_exhaustion` — PASS.
- `test_size_limit` — PASS.
- `test_concurrent_bundles` — PASS.
- `test_pickle_and_npz_rejected` — PASS.

## tests.test_input_data_cli

- `test_cli_dispatch[89-download_tsyganenko_inputs]` — PASS.
- `test_cli_dispatch[96-download_tsyganenko_inputs]` — PASS.
- `test_cli_dispatch[15B-download_ta15_inputs]` — PASS.
- `test_cli_dispatch[nrlmsis-download_atmosphere_inputs]` — PASS.
- `test_cli_bad_option` — PASS.
- `test_cli_worker_timeout` — PASS.

## tests.test_input_recovery

- `test_failure_then_recovery_preserves_previous_bundle[timeout-89]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[timeout-96]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[timeout-15B]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[timeout-nrlmsis]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[404-89]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[404-96]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[404-15B]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[404-nrlmsis]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[503-89]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[503-96]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[503-15B]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[503-nrlmsis]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[malformed-89]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[malformed-96]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[malformed-15B]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[malformed-nrlmsis]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[missing-89]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[missing-96]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[missing-15B]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[missing-nrlmsis]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[disk-89]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[disk-96]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[disk-15B]` — PASS.
- `test_failure_then_recovery_preserves_previous_bundle[disk-nrlmsis]` — PASS.
- `test_transient_503_recovers_within_attempt_budget[89]` — PASS.
- `test_transient_503_recovers_within_attempt_budget[96]` — PASS.
- `test_transient_503_recovers_within_attempt_budget[15B]` — PASS.
- `test_transient_503_recovers_within_attempt_budget[nrlmsis]` — PASS.

## tests.test_replay_contract

- `test_replay_atmosphere_only_preserves_dataset[SW-All.csv-https://celestrak.org/SpaceData/SW-All.csv]` — PASS.
- `test_replay_atmosphere_only_preserves_dataset[SW-Last5Years.csv-https://celestrak.org/SpaceData/SW-Last5Years.csv]` — PASS.
- `test_replay_rejects_invalid_evidence[hash]` — PASS.
- `test_replay_rejects_invalid_evidence[url]` — PASS.
- `test_replay_rejects_invalid_evidence[missing]` — PASS.

## tests.test_standalone

- `test_gt_import_is_never_requested` — PASS.
- `test_pickle_not_executed[<lambda>]` — PASS.
- `test_pickle_not_executed[load_ta15_inputs]` — PASS.
- `test_pickle_not_executed[load_atmosphere_inputs]` — PASS.
- `test_cli_can_run_without_repo_on_path` — PASS.

## tests.test_ta15_inputs

- `test_order_precision_flags` — PASS.
- `test_provider_interpolation_opt_in` — PASS.
- `test_reject_bad_inputs[body0]` — PASS.
- `test_reject_bad_inputs[body1]` — PASS.
- `test_reject_bad_inputs[body2]` — PASS.
- `test_reject_bad_inputs[body3]` — PASS.
- `test_reject_bad_inputs[<html>error</html>]` — PASS.
- `test_reject_bad_inputs[body5]` — PASS.
- `test_reject_bad_inputs[2023 1 0 30 -1 4 -2 -600 -20 -10 2 100000 -20 1 1 -0.4 1.8 0.6 0.3\n]` — PASS.
- `test_invalid_boundaries[2023-01-01T00:31-2023-01-01T00:40]` — PASS.
- `test_invalid_boundaries[2023-01-01-2023-01-01]` — PASS.
- `test_invalid_boundaries[1994-01-01-1994-01-02]` — PASS.
- `test_timezone` — PASS.

## tests.test_visible_checks

- `test_status_does_not_hide_failed_or_unfinished_checks` — PASS.
- `test_html_escapes_source_error` — PASS.
- `test_junit_failure_and_skips_not_passed` — PASS.
- `test_timeout_is_bounded_and_log_preserved` — PASS.
- `test_worker_error_is_not_success` — PASS.
