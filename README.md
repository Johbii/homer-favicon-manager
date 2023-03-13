# Homer Icon Manager
Python script/daemon to automatically download favicons for services in [Homer](https://github.com/bastienwirtz/homer) config files.


## Getting Started
### Using Venv
Initialize Python Virtual Environment
```
python -m venv ./.venv
```


Activate Virtual Environment
```
source ./.venv/bin/activate
```


Install Requirements to Virtual Environment
```
pip install -r ./requirements.txt
```

Run script
```
usage: app.py [-h] [-c CONFIG] [-d WORKDIR] [-o OUTPUT] [-D {0,1}] [--verify-ssl {0,1}] [--debug {0,1}]

options:
  -h, --help            show this help message and exit
  -c CONFIG, --config CONFIG
                        path to homer config file
  -d WORKDIR, --workdir WORKDIR
                        path to managed work directory
  -o OUTPUT, --output OUTPUT
                        path to managed config file output
  -D {0,1}, --daemon {0,1}
                        controls whether to enable daemon mode for watching config changes
  --verify-ssl {0,1}    verify certificates for HTTPS connections
  --debug {0,1}         enable or disable debug mode
```


### Using Docker Compose
Sample `docker-compose.yml` file for running Homer + homer-favicon-manager included
```
version: "3.4"
services:
  favicon-manager:
    image: ghcr.io/johbii/homer-favicon-manager:latest
    build:
      context: .
    environment:
      - VERIFY_SSL=0
    volumes:
      - ./vol:/data
  homer:
    image: b4bz/homer:latest
    volumes:
      - ./vol:/www/assets
    ports:
      - 8080:8080
    user: 1000:1000
    environment:
      - INIT_ASSETS=0

```


Copy your homer config.yml file to a new folder so it can be mounted by Docker

Typical volume setup
```
./vol
├── config.yml <-- *AUTO-GENERATED* no need to create this file
├── managed <-- images will go here
└── source
    └── config.yml <-- place your current homer config.yml here

2 directories, 2 files
```


Then run with
```
docker compose up -d
```


The following environment variables are available to change the functionality of the container


- `DAEMON_ENABLED={0,1}`
 *Enable or disable daemon mode for watching config changes*

- `VERIFY_SSL={0,1}`
 *Verify certificates for HTTPS connections—Set to 0 if you want to use self-signed certificates*

- `DEBUG={0,1}`
 *Enable or disable debug messages*
