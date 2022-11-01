#%%
import asyncio
import base64
import functools
import os
import time

import aiohttp
import nest_asyncio

nest_asyncio.apply()


(
    graph_api_headers,
    rest_api_headers,
) = [""] * 2


def timer(func):
    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            await func(*args, **kwargs)
            print(f"total runtime for async func: {time.time() - start_time}")

        return wrapper
    else:

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            func(*args, **kwargs)
            print(f"total runtime for sync func: {time.time() - start_time}")

        return wrapper


def get_api_headers_decorator(func):
    @functools.wraps(func)
    async def wrapper(session, *args, **kwargs):
        return {
            "Authorization": f"Basic {base64.b64encode(bytes(os.environ[args[0]], 'utf-8')).decode('utf-8')}"
            if "PAT" in args[0]
            else f"Bearer {os.environ[args[0]] if 'EA' in args[0] else await func(session, *args, **kwargs)}",
            "Content-Type": "application/json-patch+json"
            if "PAT" in args[0]
            else "application/json",
        }

    return wrapper


@get_api_headers_decorator
async def get_api_headers(session, *args, **kwargs):
    oauth2_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    oauth2_body = {
        "client_id": os.environ[args[0]],
        "client_secret": os.environ[args[1]],
        "grant_type": "client_credentials",
        "scope" if "GRAPH" in args[0] else "resource": args[2],
    }
    async with session.post(
        url=args[3], headers=oauth2_headers, data=oauth2_body
    ) as resp:
        return (await resp.json())["access_token"]


@timer
async def main(params):
    global graph_api_headers, rest_api_headers
    async with aiohttp.ClientSession() as session:
        (graph_api_headers, rest_api_headers,) = await asyncio.gather(
            *(get_api_headers(session, *param) for param in params)
        )


if __name__ == "__main__":
    params = [
        [
            "GRAPH_CLIENT_ID",
            "GRAPH_CLIENT_SECRET",
            "https://graph.microsoft.com/.default",
            f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}/oauth2/v2.0/token",
        ],
        [
            "REST_CLIENT_ID",
            "REST_CLIENT_SECRET",
            "https://management.azure.com",
            f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}/oauth2/token",
        ],
    ]
    asyncio.run(main(params))


#%%
import pandas as pd
import requests
from IPython.display import display

subscription = ""  # Prod
subscription = ""  # Non-Prod


url = f"https://management.azure.com/subscriptions/{subscription}/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01"
response = requests.get(url=url, headers=rest_api_headers).json()["value"]

df_rbac = pd.DataFrame(
    [
        {
            k: v if i else v.split("/")[-1]
            for i, (k, v) in enumerate(user["properties"].items())
        }
        for user in response
    ]
)
df_rbac = df_rbac[df_rbac["principalType"] == "ServicePrincipal"].reset_index(drop=True)
display(df_rbac.head())
print(df_rbac.shape)
#%%
tables = pd.read_html(
    "https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles"
)
display(tables[0].head())
print(tables[0].shape)
#%%
df = pd.merge(
    left=df_rbac, right=tables[0], left_on="roleDefinitionId", right_on="ID", how="left"
)
display(df.head())
print(df.shape)
#%%
async def fetch_app_name(session, upn):
    async with session.get(
        url=f"https://graph.microsoft.com/v1.0/servicePrincipals/{upn}",
        headers=graph_api_headers,
    ) as resp:
        return (await resp.json())["appDisplayName"]


async with aiohttp.ClientSession() as session:
    app_names = await asyncio.gather(
        *(fetch_app_name(session, upn) for upn in df["principalId"])
    )
    print(app_names)

df["displayName"] = pd.DataFrame({"displayName": app_names})
display(df.head())
print(df.shape)
#%%
async def fetch_app_name(session, upn):
    async with session.get(
        url=f"https://graph.microsoft.com/v1.0/servicePrincipals/{upn}",
        headers=graph_api_headers,
    ) as resp:
        return (await resp.json())["appId"]


async with aiohttp.ClientSession() as session:
    app_ids = await asyncio.gather(
        *(fetch_app_name(session, upn) for upn in df["principalId"])
    )
    print(app_ids)

df["appId"] = pd.DataFrame({"app_ids": app_ids})
display(df.head())
print(df.shape)
#%%
import requests

values = []
links = []
with requests.Session() as session:
    response = session.get(
        f"https://graph.microsoft.com/v1.0/applications", headers=graph_api_headers
    ).json()
    while link := response.get("@odata.nextLink"):
        print(response.keys())
        links.append(link)
        values.append(response.get("value"))
        response = session.get(link, headers=graph_api_headers).json()
    print("finished")

apps = [v for value in values for v in value]
df_apps = pd.DataFrame(apps)
display(df_apps.head(2))
print(df_apps.shape)
#%%
df_final = pd.merge(df, df_apps, on="appId")
df_final = df_final[
    [
        "displayName_x",
        "displayName_y",
        "appId",
        "id",
        "passwordCredentials",
        "Built-in role",
        "scope",
    ]
]
df_final["passwordCredentials"] = pd.to_datetime(
    df_final["passwordCredentials"].map(lambda k: k[0]["endDateTime"]),
    format="%Y-%m-%dT%H:%M:%S%z",
)
display(df_final)
print(df_final.shape)
#%%
df_final.rename({"passwordCredentials": "secretExpiryDate"}, axis=1, inplace=True)
df_final.rename({"id": "objectId"}, axis=1, inplace=True)
df_final.sort_values(by="secretExpiryDate", ascending=False, inplace=True)
df_final.reset_index(drop=True, inplace=True)
