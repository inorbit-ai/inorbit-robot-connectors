# Config As Code examples

The files in this folder contain example [configuration as code](https://developer.inorbit.ai/docs#summary) objects, useful to unlock the full capabilities of the MiR <> InOrbit Connector. They can be managed through the [InOrbit CLI](https://developer.inorbit.ai/docs#using-the-inorbit-cli).
Please note that the features available on your account will depend on your [InOrbit Edition](https://www.inorbit.ai/pricing). Don't hesitate to contact support@inorbit.ai for more information.

`native_mission.yaml` holds `MissionDefinition` examples that run MiR robot actions (dock, charge, set I/O, sound, nested missions) as mission steps via the `mir_actionType` argument. See [Running MiR Actions in Missions](../README.md#-running-mir-actions-in-missions) in the connector README for the parameter value types and how to find action types.
