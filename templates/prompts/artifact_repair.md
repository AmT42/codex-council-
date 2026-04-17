Your previous {{role}} artifacts for turn {{turn_name}} were not accepted because they failed schema validation.

Validation error:
{{validation_error}}

Rewrite only these files:
- {{message_path}}
- {{status_path}}
{{extra_paths}}

Keep the status JSON aligned with the required schema from the main turn prompt for this role.
Do not create extra files. After rewriting the required artifacts, end your turn.
