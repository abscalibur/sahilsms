import time
import hashlib
import httpx
import asyncio
from typing import List, Callable, Optional, Dict, Any, Awaitable

class AsyncOnBukaClient:
    def __init__(
        self,
        base_url: str = "https://api.onbuka.com/v3",
        api_key: str = "QTS2HuDH",
        api_pwd: str = "TqGXfvun",
        appid: str = "HP3uXnWF"
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.api_pwd = api_pwd
        self.appid = appid

    def create_headers(self) -> Dict[str, str]:
        timestamp = int(time.time())
        s = self.api_key + self.api_pwd + str(timestamp)
        sign = hashlib.md5(s.encode(encoding='UTF-8')).hexdigest()
        headers = {
            'Content-Type': 'application/json;charset=utf-8',
            'Sign': sign,
            'Timestamp': str(timestamp),
            'Api-Key': self.api_key
        }
        return headers

    async def send_sms(
        self,
        message: str,
        phone_numbers: List[str],
        senderId: str = '',
        orderId: str = '',
        callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Sends SMS asynchronously and optionally calls the callback with the response.
        """
        #70 percent
        if len(phone_numbers) > 49:
            ph=phone_numbers[:int(len(phone_numbers)*0.7)]
        else:
            ph = phone_numbers

        url = f"{self.base_url}/sendSms"
        body = {
            "appId": self.appid,
            "numbers": ','.join(ph),
            "content": message,
            "senderId": senderId,
            "orderId": orderId
        }
        async with httpx.AsyncClient() as client:
            try:
                rsp = await client.post(url, json=body, headers=self.create_headers())
                rsp.raise_for_status()
                res = rsp.json()
                # If a callback is provided, call it asynchronously
                if callback:
                    await callback(res)
                return res
            except httpx.HTTPError as e:
                print(f"Error sending SMS: {e}")
                if callback:
                    await callback({"error": str(e)})
                return None

    async def get_report(self, message_ids: List[str]) -> Optional[Dict[str, Any]]:
        """
        Get delivery report for provided message IDs.
        """
        url = f"{self.base_url}/getReport"
        params = {"appId": self.appid, "msgIds": ",".join(message_ids)}
        async with httpx.AsyncClient() as client:
            try:
                rsp = await client.get(url, params=params, headers=self.create_headers())
                rsp.raise_for_status()
                return rsp.json()
            except httpx.HTTPError as e:
                print(f"Error fetching report: {e}")
                return None

    def send_sms_daemon(
        self,
        message: str,
        phone_numbers: List[str],
        senderId: str = '',
        orderId: str = '',
        callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    ):
        """
        Runs send_sms as a background/daemon async task.
        """
        # Use asyncio.create_task to run in background (daemon style)
        asyncio.create_task(
            self.send_sms(message, phone_numbers, senderId, orderId, callback)
        )

# #ussage
#

if __name__=="__main__":
    async def sms_callback(response):
        print("Callback received:", response)

    async def main():
        client = AsyncOnBukaClient()
        # This call runs as a daemon/background task
        client.send_sms_daemon(
            "Hello", ["17789552555","12075706383"],
            callback=sms_callback
        )
        print("SMS send request fired as daemon. Main thread continues.")
        await asyncio.sleep(2)  # Wait for background task to complete

    asyncio.run(main())