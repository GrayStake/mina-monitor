from typing import final
import docker
import requests
import logging

from time import sleep

logging.basicConfig(
    format="[%(asctime)s] %(levelname)s:%(message)s", level=logging.DEBUG
)
client = docker.from_env()

MAX_RETRY_COUNT = 5
GRAPHQL_URI = "http://node:3085/graphql"
INITIAL_STATUS_COUNT = {
    "SYNCED": 0,
    "CONNECTING": 0,
    "OFFLINE": 0,
    "CATCHUP": 0,
    "BOOTSTRAP": 0,
}
STATUS_COUNT = INITIAL_STATUS_COUNT
OUTOFSYNC_COUNT = 0


class NodeOutOfSyncException(Exception):
    """Exception for triggering the node restart."""

    pass


class NodeNotReachableException(Exception):
    """Exception for waiting the node to be reachable."""

    pass


def check_mina_node_status():
    """
    Fetch Mina node status using the GraphQL client.
    """
    logging.debug("Fetching node status")
    global MAX_RETRY_COUNT
    global GRAPHQL_URI
    global STATUS_COUNT

    retry_count = 0

    while retry_count < MAX_RETRY_COUNT:
        # Try fetching the node status for MAX_RETRY_COUNT iterations.
        query = """
        {
            daemonStatus {
                syncStatus
                uptimeSecs
                blockchainLength
                highestBlockLengthReceived
                highestUnvalidatedBlockLengthReceived
                nextBlockProduction {
                    times {
                        startTime
                    }
                }
            }
        }
        """

        # Fetch node status using the GraphQL API
        try:
            r = requests.post(
                GRAPHQL_URI,
                json={"query": query},
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
        except requests.exceptions.ConnectionError:
            # Node is not reachable.
            # Raise NodeOutOfSyncException in order to skip a few syncs
            # and give node time to be reachable
            raise NodeNotReachableException()

        # Check response status
        if r.status_code == 200:
            logging.debug("Status fetched successfully")
            response = r.json()["data"]["daemonStatus"]
            logging.debug(response)

            # Node sync status
            sync_status = response["syncStatus"]
            # Node uptime (in seconds)
            uptime = response["uptimeSecs"]
            # Blockchain length
            blockchain_length = response["blockchainLength"]
            # Highest block
            highest_block = response["highestBlockLengthReceived"]
            # Highest unvalidated block
            highest_unvalidated_block = response[
                "highestUnvalidatedBlockLengthReceived"
            ]
            # Compute difference between unvalidated and validated blocks
            blocks_validated_diff = highest_unvalidated_block - highest_block

            # Increment status count
            STATUS_COUNT[sync_status] += 1
            logging.debug(STATUS_COUNT)

            if STATUS_COUNT["CONNECTING"] > 60:
                logging.error(
                    "Node has been too long in the CONNECTING state. (more than 5 minutes"
                )
                raise NodeOutOfSyncException()

            if STATUS_COUNT["CATCHUP"] > 540:
                logging.debug(
                    "Node has been too long in the CATHUP state (more than 45 minutes)."
                )
                raise NodeOutOfSyncException()

            if STATUS_COUNT["BOOTSTRAP"] > 240:
                logging.error(
                    "Node has been too long in the BOOTSTRAP state (more than 20 minutes)."
                )
                raise NodeOutOfSyncException()

            if sync_status == "BOOTSTRAP":
                logging.debug("Node is bootstrapping...")
                return

            if blocks_validated_diff > 2:
                logging.error(
                    "Difference between highest validated block and highest unvalidated block. (delta > 2)"
                )
                raise NodeOutOfSyncException()

            logging.info("Node is synced.")
            return

        # Retry
        retry_count += 1
        logging.debug("Node status check failed. Retrying...")

    # Raise NodeOutOfSyncException in order to restart the node
    raise NodeOutOfSyncException()


def restart_node():
    """Restart Mina node"""
    logging.debug("Restarting node")

    global STATUS_COUNT
    global INITIAL_STATUS_COUNT
    global client

    for item in client.containers.list():
        if "node" in item.name or "sidecar" in item.name:
            item.stop()

    STATUS_COUNT = INITIAL_STATUS_COUNT


def start_monitor():
    """Main event loop"""
    logging.info("mina-monitor started")

    global OUTOFSYNC_COUNT

    while True:
        try:
            check_mina_node_status()
        except NodeOutOfSyncException:
            OUTOFSYNC_COUNT += 1
            logging.error(
                "Node is out of sync. (OUTOFSYNC_COUNT={})".format(OUTOFSYNC_COUNT)
            )
            restart_node()
            sleep(30)
        except NodeNotReachableException:
            logging.error("Node is not reachable.")
            sleep(10)
        finally:
            sleep(5)


if __name__ == "__main__":
    start_monitor()
