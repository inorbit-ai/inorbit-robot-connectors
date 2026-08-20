<!--
SPDX-FileCopyrightText: 2026 InOrbit, Inc.

SPDX-License-Identifier: MIT
-->

# Configuration as Code

The files in this folder contain [configuration as code](https://developer.inorbit.ai/docs#configuration-as-code)
objects that unlock the full capabilities of the Gausium Open Platform <> InOrbit connector.
Features available on your account depend on your [InOrbit Edition](https://www.inorbit.ai/pricing);
contact [support@inorbit.ai](mailto:support@inorbit.ai) for more information.

## Applying

1. Install and authenticate the [InOrbit CLI](https://developer.inorbit.ai/docs#using-the-inorbit-cli).
2. Tag your Gausium robots in InOrbit and replace every `<ACCOUNT_ID>` / `<TAG_ID>`
   placeholder in these files with your account ID and the tag ID.
3. Apply each file:

```bash
inorbit apply -f actions.yaml
inorbit apply -f data_sources.yaml
inorbit apply -f mission_tracking.yaml
inorbit apply -f status_definition.yaml
inorbit apply -f footprint.yaml
```

| File | Contents |
|------|----------|
| `actions.yaml` | UI actions for the connector's custom commands (submit task, task command, navigate) |
| `data_sources.yaml` | Definitions for the key-values published per robot |
| `mission_tracking.yaml` | Mission tracking from the `mission_tracking` event |
| `status_definition.yaml` | Fleet Status rules (battery, API connectivity) |
| `footprint.yaml` | Phantas robot footprint geometry |
