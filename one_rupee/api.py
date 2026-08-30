import requests


def get_health(api_url):
    response = requests.get(
        f"{api_url.rstrip('/')}/health",
        timeout=10
    )

    response.raise_for_status()

    return response.json()


def get_stats(api_url):
    response = requests.get(
        f"{api_url.rstrip('/')}/stats",
        timeout=10
    )

    response.raise_for_status()

    return response.json()


def get_membership_status(api_url, customer_id):
    response = requests.get(
        f"{api_url.rstrip('/')}/membership-status/{customer_id}",
        timeout=10
    )

    response.raise_for_status()

    return response.json()
