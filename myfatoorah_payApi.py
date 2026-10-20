import aiohttp
import hashlib
import json
import uuid
import asyncio  # For async sleep


configs = json.load(open('config.json', encoding='utf-8'))


# API_KEY = configs["TEST_FATOORAH_API_KEY"]
# BASE_URL = "https://apitest.myfatoorah.com"


API_KEY = configs["FATOORAH_API_KEY"]
BASE_URL = "https://api-sa.myfatoorah.com/"


async def myfatoorah_make_request(url: str, data: dict):
    async with aiohttp.ClientSession(headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }) as session:
        async with session.post(url=url, json=data) as response:
            response_text = await response.text()  # Get the full response content as text
            if not response.ok:
                print(f"Error {response.status}: {response_text}")  # Debugging info
                raise ValueError(response.reason)
            return await response.json()

async def create_invoice_myfatoorah(amount, user_id, currency="SAR"):
    invoice_data = await myfatoorah_make_request(
        url=f"{BASE_URL}/v2/SendPayment",
        data={
            "InvoiceValue": amount,
            "CurrencyIso": currency,
            "CustomerName": "Telegram Customer",
            "CustomerMobile": "",
            "CustomerEmail": f"TG_{user_id}@TG.com",
            # "CallBackUrl": "https://yourcallbackurl.com",
            # "ErrorUrl": "https://yourerrorurl.com",
            "Language": "en",  # Can be "ar" or "en"
            "CustomerReference": str(uuid.uuid4()),
            "DisplayCurrencyIso": currency,
            "NotificationOption": "ALL"
        }
    )
    
    # Access the correct key 'InvoiceURL' instead of 'PaymentURL'
    return [invoice_data['Data']['InvoiceId'], invoice_data['Data']['InvoiceURL'], invoice_data]

async def check_invoice_status_myfatoorah(invoice_id):
    invoice_status_data = await myfatoorah_make_request(
        url=f"{BASE_URL}/v2/GetPaymentStatus",
        data={
            "Key": invoice_id,
            "KeyType": "InvoiceId"
        }
    )

    if invoice_status_data['Data']['InvoiceStatus'] == 'Paid':
        return [True, invoice_status_data]
    else:
        return [False, invoice_status_data]


# async def main():
#     # Create an invoice
#     data = await create_invoice_myfatoorah(50)
#     print(f"Invoice created: {data}")
    
#     # Check invoice status periodically
#     for x in range(500):
#         paid = await check_invoice_status_myfatoorah(data[0])
#         print(f"Check {x + 1}: Paid status: {paid[0]}")
#         await asyncio.sleep(20)  # Asynchronous sleep for 10 seconds


# # Running the async main function
# if __name__ == "__main__":
#     asyncio.run(main())
