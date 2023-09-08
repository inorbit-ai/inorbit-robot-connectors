# Contributing

Contributions are welcome, and they are greatly appreciated! Every little bit
helps, and credit will always be given.

## Get Started

Ready to contribute? Here's how to set up `inorbit-robot-connectors` for local development.

1. Fork the `inorbit-robot-connectors` repo on GitHub.

2. Clone your fork locally:

    ```bash
    git clone git@github.com:{your_name_here}/inorbit-robot-connectors.git
    ```

3. If adding a new connector (yay!), create a directory for it under the repo root using <vendor_connector> or <vendor_model_connector>. Add your new connector's code to it.

    If updating an existing connector (thanks!), change directory to the connector you'd like to update.

    It is recommended to work in a virtualenv or anaconda environment:

    ```bash
    cd inorbit-robot-connectors/src/<name_connector>
    virtualenv venv
    . venv/bin/activate
    pip install -r requirements.txt
    ```

4. Create a branch for local development:

    ```bash
    git checkout -b {your_development_type}/short-description
    ```

    Ex: feature/mybot-connector or bugfix/otto-report-errors<br>
    Now you can make your changes locally.

5. When you're done making changes, check that your changes pass linting with pre-commit:

    Install [pre-commit](https://pre-commit.com/) in your computer and then set it up by running `pre-commit install` at the root of the cloned project.

6. Commit your changes and push your branch to GitHub:

    ```bash
    git add .
    git commit -m "Resolves gh-###. Your detailed description of your changes."
    git push origin {your_development_type}/short-description
    ```

7. Submit a pull request through the GitHub website.

Note: Any contribution that you make to this repository will be under the MIT license, as dictated by that [license](https://opensource.org/licenses/MIT).
