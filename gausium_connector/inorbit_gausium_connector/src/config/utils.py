from ruamel.yaml import YAML

yaml = YAML()
yaml.indent(mapping=2, sequence=4, offset=2)


def write_yaml(config_filename: str, config_file_content) -> None:
    """
    Writes configuration file content to the given configuration file.
    """

    with open(file=config_filename, mode="w") as f:
        yaml.dump(config_file_content, f)
