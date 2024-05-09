# Contributing

Contributions are welcome, and they are greatly appreciated! Every little bit helps, and credit will always be given.

## Get Started

Ready to contribute? Here's how to set up `inorbit-instock-connector` for local development.

1. Fork the `inorbit-robot-connectors` repo on GitHub.

2. Clone your fork locally:

    ```bash
    git clone git@github.com:{your_name_here}/inorbit-robot-connectors.git
    ```

3. Install the project in editable mode. (It is also recommended to work in a virtualenv or anaconda environment):

    ```bash
    cd inorbit-robot-connectors/instock_connector
    virtualenv .venv
    source .venv/bin/activate
    pip install -r reqirements-dev.txt
    ```

4. Create a branch for local development:

    ```bash
    git checkout -b {your_development_type}/short-description
    ```

   Ex: feature/read-tiff-files or bugfix/handle-file-not-found<br>
   Now you can make your changes locally.

5. When you're done making changes, check that your changes pass linting and tests, including testing other Python
   versions with tox:

    ```bash
    tox
    ```

6. Commit your changes and push your branch to GitHub:

    ```bash
    git add .
    git commit -m "Resolves #xyz. Your detailed description of your changes."
    git push origin {your_development_type}/short-description
    ```

7. Submit a pull request through the GitHub website.

## Deploying

A reminder for the maintainers on how to deploy.
Make sure you are on the `main` branch and have pulled the latest changes.

Setup `virtualenv` with `dev` requirements:

```bash
cd inorbit-robot-connectors/instock_connector
virtualenv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

Then run `bump2version` and choose the part of the version to be bumped, and don't forget to push changes and tags:

```bash
bump2version patch # possible: major / minor / patch
git push
git push --tags
```

This will release a new package version on Git + GitHub and publish to PyPI.