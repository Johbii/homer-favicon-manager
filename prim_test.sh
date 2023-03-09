#!/usr/bin/env sh
sleep 1 # ensure the unix timestamp has had time to continue
id=`sudo docker compose ps -q favicon-manager`
sudo docker exec --user root $id /usr/bin/env sh -c "x=`date +%s` && x=/www/assets/source/test_\$x && mkdir -p \$x && touch \$x/config.yml"
