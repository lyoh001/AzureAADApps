import asyncio
import base64
import datetime
import functools
import logging
import os
import tempfile
import time

import aiohttp
import azure.functions as func
import matplotlib.pyplot as plt
import pandas as pd
import pytz
from pandas_profiling import ProfileReport
from PIL import Image


def timer(func):
    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            result = await func(*args, **kwargs)
            logging.info(
                f"total execution time for async {func.__name__}: {time.time() - start_time}"
            )
            if result:
                return result

        return wrapper
    else:

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            logging.info(
                f"total execution time for sync {func.__name__}: {time.time() - start_time}"
            )
            if result:
                return result

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


async def fetch(session, graph_api_headers, url, role=None):
    async with session.get(url=url, headers=graph_api_headers) as resp:
        return (await resp.json())["value"], role


@timer
async def main(mytimer: func.TimerRequest) -> None:
    logging.info("******* Starting main function *******")
    attachment, roles_df = {}, pd.DataFrame()
    async with aiohttp.ClientSession() as session:
        graph_api_headers = next(
            iter(
                await asyncio.gather(
                    *(
                        get_api_headers(session, *param)
                        for param in [
                            [
                                "GRAPH_CLIENT_ID",
                                "GRAPH_CLIENT_SECRET",
                                "https://graph.microsoft.com/.default",
                                f"https://login.microsoftonline.com/{os.environ['TENANT_ID']}/oauth2/v2.0/token",
                            ]
                        ]
                    )
                )
            )
        )

        roles = next(
            iter(
                await asyncio.gather(
                    fetch(
                        session,
                        graph_api_headers,
                        "https://graph.microsoft.com/v1.0/directoryRoles",
                    )
                )
            )
        )
        for payload, role in await asyncio.gather(
            *(
                fetch(
                    session,
                    graph_api_headers,
                    f"https://graph.microsoft.com/v1.0/directoryRoles/{role['id']}/members",
                    role["displayName"],
                )
                for role in next(iter(roles))
            )
        ):
            df = pd.DataFrame(payload)
            df["roles"] = [role] * len(payload)
            roles_df = roles_df.append(df)

        roles_df = roles_df[
            [
                "userPrincipalName",
                "displayName",
                "roles",
                "jobTitle",
                "description",
                "id",
            ]
        ]
        roles_df.sort_values(by=["userPrincipalName"], inplace=True)
        attachment["csv"] = roles_df.to_csv(index=False)

        with tempfile.TemporaryDirectory() as tempdir_path:
            report = ProfileReport(
                roles_df,
                title="VICGOV AAD Roles",
                pool_size=1,
                progress_bar=False,
                explorative=True,
                correlations=None,
            )
            report.to_file((report_path := os.path.join(tempdir_path, "report.html")))
            with open(report_path, "r") as file_reader:
                attachment["html"] = file_reader.read()

        role_df = (
            roles_df.groupby("roles")
            .count()["userPrincipalName"]
            .sort_values(ascending=False)
            .head(7)
        )
        role_df.index

        plt.style.use("Solarize_Light2")
        plt.figure(figsize=(8.2, 8.2)).patch.set_facecolor("#b6dbeb")
        ax = plt.subplot(1, 1, 1)
        ax.pie(
            role_df,
            labels=role_df.index,
            autopct="%1.1f%%",
            shadow=False,
            startangle=90,
            textprops={"fontsize": 7},
        )
        plt.title("The Top 7 most UPN assigned VICGOV AAD Roles")
        plt.xlabel("")
        plt.xticks(rotation="90")
        plt.ylabel("")
        plt.legend(loc="lower left", labels=role_df.index)
        plt.tight_layout()

        with tempfile.TemporaryDirectory() as tempdir_path:
            plt.savefig(
                (pie_graph_path := os.path.join(tempdir_path, "pie_graph.jpg")), dpi=100
            )
            Image.open(pie_graph_path).resize((590, 590), Image.ANTIALIAS).save(
                (pie_graph_path := os.path.join(tempdir_path, "pie_graph_resized.jpg"))
            )
            with open(pie_graph_path, "rb") as graph_reader:
                attachment["graph"] = base64.b64encode(graph_reader.read()).decode(
                    "ascii"
                )

        attachment["time"] = str(
            datetime.datetime.now(pytz.timezone("Australia/Melbourne"))
        )[:-13]

        async with session.post(
            url=os.environ["LOGICAPP_URI"],
            json=attachment,
        ) as resp:
            logging.info(
                f"******* Finishing main function with status {resp.status} *******"
            )
