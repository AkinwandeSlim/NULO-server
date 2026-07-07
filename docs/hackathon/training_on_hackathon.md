Setup & Authentication
Knowledge checks · 0 / 2
0%
Nomba uses OAuth 2.0 client_credentials for server-to-server calls. You exchange your clientId and clientSecret for a short-lived access token (1 hour) and attach it as a Bearer token on every subsequent request, plus the accountId header.

POST
/auth/token/issue
Issue an access token for your account
POST
/auth/token/refresh
Refresh an access token before it expires
Issuing a token
Node.js
Python
Copy
import os, requests

res = requests.post(
    "https://api.nomba.com/v1/auth/token/issue",
    headers={
        "Content-Type": "application/json",
        "accountId": os.environ["NOMBA_ACCOUNT_ID"],
    },
    json={
        "grant_type": "client_credentials",
        "client_id": os.environ["NOMBA_CLIENT_ID"],
        "client_secret": os.environ["NOMBA_CLIENT_SECRET"],
    },
)
print("access_token:", res.json()["data"]["access_token"])
Cache your tokens
Tokens are valid for 60 minutes. Cache in memory or Redis and refresh at the 55-minute mark — do not request a fresh token per call.

Required headers on every authenticated call
Header	Value
Authorization	Bearer <access_token>
accountId	Your Nomba account ID
Content-Type	application/json
Knowledge check
Which OAuth 2.0 grant type does a server-side Nomba integration use?


password

authorization_code

client_credentials

implicit
Knowledge check
Your worker dispatches 50 background jobs that each call Nomba. What is the right token strategy?


Request a fresh token at the start of every job

Share one cached token and refresh near the 55-minute mark

Reuse the access token forever — it never expires

Store the token in the browser localStorage of your admin















Sub-accounts
Knowledge checks · 0 / 1
0%
Sub-accounts let you split a single Nomba merchant into many logical accounts — perfect for marketplaces, multi-tenant SaaS, or any product where funds must be tracked per seller, per branch, or per project. Each sub-account has its own balance and its own virtual accounts.

POST
/accounts/sub-accounts
Create a new sub-account
GET
/accounts/sub-accounts
List sub-accounts under your parent
GET
/accounts/sub-accounts/{id}/balance
Fetch the available balance of a sub-account
Node.js
Python
Copy
const sub = await nomba.post("/accounts/sub-accounts", {
  accountName: "Seller — Adaeze Kitchen",
  accountRef: "seller_adaeze_001",
});
Use stable refs
Pass your own accountRef so you can look up Nomba sub-accounts from your database without storing Nomba IDs as primary keys.

Knowledge check
Why should you set your own accountRef when creating a sub-account?


It's required by the API

So you can look up the sub-account from your DB without storing Nomba IDs

Nomba uses it as the bank account number

It controls the sub-account's daily transfer limit






































Online Checkout
Knowledge checks · 0 / 2
0%
The Checkout API generates a hosted payment page. You POST the order, get a checkoutUrl back, and redirect the customer. Nomba handles card entry, 3-D Secure, OTPs, and PCI scope. You receive a webhook when payment completes.

POST
/checkout/order
Create a hosted checkout session
GET
/checkout/order/{orderReference}
Look up a checkout session status
Node.js
Python
Copy
order = nomba.post("/checkout/order", json={
    "order": {
        "orderReference": f"ord_{uuid4()}",
        "amount": 250000,
        "currency": "NGN",
        "callbackUrl": "https://yourapp.com/payment/return",
        "customerId": "cus_8821",
        "customerEmail": "ada@example.com",
    },
})
return redirect(order["data"]["checkoutUrl"])
Amounts are in kobo
₦1.00 is 100 kobo. Sending 25 will charge 25 kobo, not ₦25. Always multiply by 100.

Try it
POST /checkout/order
Node
Python
Amount (₦)
2500
Currency
NGN
Customer email
ada@example.com
Order reference
ord_demo_001
await nomba.post("/checkout/order", {
  order: {
    orderReference: "ord_demo_001",
    amount: 2500 * 100,   // kobo
    currency: "NGN",
    customerEmail: "ada@example.com",
    callbackUrl: "https://yourapp.com/payment/return",
  },
});
Run mock request
200 OK · simulated
Knowledge check
The customer is paying ₦1,500.00. What value goes in the `amount` field?


1500

150000

15.00

15000
Order the steps
Put a hosted-checkout payment in the right order.
shuffle
1
You redirect the customer to the checkoutUrl


2
Nomba posts payment_success webhook to your server


3
Your server POSTs /checkout/order and gets a checkoutUrl


4
Customer clicks Pay in your app


5
Your server verifies the signature, marks the order paid, and fulfils


6
Customer enters card and 3-D Secure on Nomba's hosted page


Check order
← Sub-accounts



























Tokenized Cards & Recurring Payments
Knowledge checks · 0 / 1
0%
After a successful checkout, Nomba returns a card token representing the customer's card. You can charge that token later — for subscriptions, top-ups, or one-click re-orders — without the customer re-entering details. Tokens are scoped to your merchant and cannot be used elsewhere.

POST
/tokenized-card/charge
Charge a previously saved card token
GET
/tokenized-card/list
List saved tokens for a customer
DELETE
/tokenized-card/{tokenId}
Revoke a stored card token
Node.js
Python
Copy
nomba.post("/tokenized-card/charge", json={
    "amount": 500000,
    "currency": "NGN",
    "cardId": "tok_5fa12b...",
    "customerId": "cus_8821",
    "merchantTxRef": f"sub_2026_03_{customer_id}",
})
Subscriptions are your job
Nomba does not run the schedule — you do. Store the token, run a cron, and charge on your billing cycle. Always send a unique merchantTxRef per attempt to make retries idempotent.

Knowledge check
Why must merchantTxRef be unique per charge attempt?


So Nomba can bill you per ref

So duplicate retries are deduplicated (idempotency) and you don't double-charge

So the customer sees it on their statement

Tokens expire when refs repeat
← Online Checkout
Answer the 1 knowledge check above to continue







Virtual Accounts
Knowledge checks · 0 / 1
0%
Virtual accounts are dedicated NUBAN accounts you can issue to any customer or invoice. When the customer transfers to that NUBAN from any Nigerian bank, you get a webhook with the amount, sender, and your reference. Perfect for invoicing, escrow, and bank-transfer checkout flows.

POST
/accounts/virtual
Create a permanent or one-time virtual account
GET
/accounts/virtual/{accountId}
Fetch virtual account details and balance
Node.js
Python
Copy
va = nomba.post("/accounts/virtual", json={
    "accountRef": "inv_9921",
    "accountName": "Acme Ltd — INV 9921",
    "expiryDate": "2026-12-31",
    "amount": 1000000,
})
Handle over- and under-payment
Even when you set an expected amount, the bank rails will accept any value. Compare amountReceived to amountExpected in your webhook handler — refund overpayments and surface short-payments to the customer.

Knowledge check
You set an expected amount of ₦10,000 on a virtual account, but only ₦5,000 lands. What should your webhook do?


Mark the invoice paid in full — Nomba reconciles the rest

Compare amountReceived to amountExpected and trigger a short-payment branch

Reject the funds and reverse the transfer

Wait 24 hours then auto-credit
Correct. Bank rails accept any value. Your handler is the only place over/under-payment is caught.
← Tokenized Cards & Recurring Payments






















Module 08
5 min read
Webhooks
Knowledge checks · 0 / 3
0%
Webhooks are how Nomba tells your server that something happened — a payment succeeded, a virtual account was funded, a transfer completed. Every webhook is signed with HMAC-SHA256 using your webhook secret. You must verify the signature before trusting the payload.

Verifying signatures
Node.js
Python
Copy
import crypto from "crypto";

app.post("/webhooks/nomba", express.raw({ type: "application/json" }), (req, res) => {
  const signature = req.header("nomba-signature");
  const expected = crypto
    .createHmac("sha256", process.env.NOMBA_WEBHOOK_SECRET!)
    .update(req.body)
    .digest("hex");

  if (signature !== expected) return res.status(401).send("bad signature");

  const event = JSON.parse(req.body.toString());
  // Idempotency: ignore if we have already processed event.requestId
  res.sendStatus(200);
});
Webhooks may fire twice
Network retries can deliver the same event multiple times. Store event.requestId in a unique index and reject duplicates — never apply a balance change twice.

Common event types
Event type	Fires when
payment_success	A checkout or token charge completes
virtual_account.funded	A NUBAN you issued receives a transfer
transfer.success	An outbound transfer settles to the recipient
transfer.failed	An outbound transfer is reversed
mandate.debit_success	A direct debit attempt clears

Think first
Before reading the answer: name two things that can go wrong if you skip signature verification.
Knowledge check
What's the first thing your webhook handler must do before doing anything else?


Parse the JSON body

Reply 200 OK so Nomba stops retrying

Verify the HMAC-SHA256 signature using your webhook secret

Look up the merchantTxRef in your database
Knowledge check
Nomba retries delivery and the same payment_success event arrives twice. How do you stay safe?


Use a database transaction

Store event.requestId in a unique index and reject duplicates

Sleep 5 seconds before processing

Filter by IP address
Signature labWhich of these is the valid nomba-signature for the payload + secret below?
Payload
{"event":"payment_success","requestId":"req_3f9a2c","data":{"merchantTxRef":"ord_8821","amount":250000,"currency":"NGN"}}
Webhook secret
whsec_demo_nomba_2026

0e8c3f1ae377e1c56a237f490eb20955656bd172147170d9b749e29efbbe6bf5

de7774f67f8b80bd8a3e4752e27748708c21a3c51940da5588e8933e9f79f779

58ee13f46d68c62780e11653ce88175c9c39dfc402a9ce857ad2beebb50aece0

aad53945391b25ff8dc3c11ff2f54cc463cfb926ff8566a72593a158b1be67e5
← Virtual Accounts

















































Webhooks
Knowledge checks · 0 / 3
0%
Webhooks are how Nomba tells your server that something happened — a payment succeeded, a virtual account was funded, a transfer completed. Every webhook is signed with HMAC-SHA256 using your webhook secret. You must verify the signature before trusting the payload.

Verifying signatures
Node.js
Python
Copy
import hmac, hashlib, os
from flask import request, abort

@app.post("/webhooks/nomba")
def nomba_webhook():
    body = request.get_data()
    signature = request.headers.get("nomba-signature")
    expected = hmac.new(
        os.environ["NOMBA_WEBHOOK_SECRET"].encode(),
        body, hashlib.sha256
    ).hexdigest()
    if signature != expected:
        abort(401)
    event = request.get_json()
    # Idempotency: ignore if we have already processed event["requestId"]
    return "", 200
Webhooks may fire twice
Network retries can deliver the same event multiple times. Store event.requestId in a unique index and reject duplicates — never apply a balance change twice.

Common event types
Event type	Fires when
payment_success	A checkout or token charge completes
virtual_account.funded	A NUBAN you issued receives a transfer
transfer.success	An outbound transfer settles to the recipient
transfer.failed	An outbound transfer is reversed
mandate.debit_success	A direct debit attempt clears

Think first
Before reading the answer: name two things that can go wrong if you skip signature verification.
Knowledge check
What's the first thing your webhook handler must do before doing anything else?


Parse the JSON body

Reply 200 OK so Nomba stops retrying

Verify the HMAC-SHA256 signature using your webhook secret

Look up the merchantTxRef in your database
Knowledge check
Nomba retries delivery and the same payment_success event arrives twice. How do you stay safe?


Use a database transaction

Store event.requestId in a unique index and reject duplicates

Sleep 5 seconds before processing

Filter by IP address
Signature labWhich of these is the valid nomba-signature for the payload + secret below?
Payload
{"event":"payment_success","requestId":"req_3f9a2c","data":{"merchantTxRef":"ord_8821","amount":250000,"currency":"NGN"}}
Webhook secret
whsec_demo_nomba_2026

0e8c3f1ae377e1c56a237f490eb20955656bd172147170d9b749e29efbbe6bf5

de7774f67f8b80bd8a3e4752e27748708c21a3c51940da5588e8933e9f79f779

58ee13f46d68c62780e11653ce88175c9c39dfc402a9ce857ad2beebb50aece0

aad53945391b25ff8dc3c11ff2f54cc463cfb926ff8566a72593a158b1be67e5
← Virtual Accounts























Transfers
Knowledge checks · 0 / 1
0%
Transfers move money out of your Nomba balance to any Nigerian bank account. Use them for payouts, refunds beyond the original card window, and treasury operations. Every transfer needs a verified recipient and a unique merchantTxRef.

POST
/transfers/bank/lookup
Resolve an account number to a name before sending
POST
/transfers/bank
Initiate a bank transfer
GET
/transfers/{merchantTxRef}
Check transfer status
Node.js
Python
Copy
lookup = nomba.post("/transfers/bank/lookup", json={
    "bankCode": "044",
    "accountNumber": "0123456789",
})
nomba.post("/transfers/bank", json={
    "amount": 1500000,
    "bankCode": "044",
    "accountNumber": "0123456789",
    "accountName": lookup["data"]["accountName"],
    "senderName": "Acme Ltd",
    "narration": "Payout — March 2026",
    "merchantTxRef": f"payout_{uuid4()}",
})
Always lookup before transfer
Sending to a wrong NUBAN can be irreversible. Display the resolved accountName to the user for confirmation before initiating the transfer.

Knowledge check
What must you do before calling /transfers/bank?


Send a ₦1 test transfer

Call /transfers/bank/lookup and confirm the resolved accountName

Email the recipient

Verify the customer's balance





















Module 10
4 min read
Direct Debits (Mandates)
Knowledge checks · 0 / 1
0%
A mandate is the customer's standing authorisation to debit their bank account on a recurring or on-demand basis. Use mandates for lending, BNPL, or any service that needs to pull funds without the customer initiating each charge. Mandates require explicit customer consent via OTP or in-app approval.

POST
/mandates/create
Create a mandate request — returns a consent URL
POST
/mandates/{mandateId}/debit
Debit a previously approved mandate
DELETE
/mandates/{mandateId}
Cancel an active mandate
Node.js
Python
Copy
mandate = nomba.post("/mandates/create", json={
    "customerId": "cus_8821",
    "maxAmount": 5000000,
    "frequency": "monthly",
    "startDate": "2026-04-01",
    "endDate": "2027-04-01",
})
# redirect customer to mandate["data"]["consentUrl"]
Respect the ceiling
Attempting to debit more than maxAmount will fail. If your billing exceeds the ceiling, create a new mandate — do not split debits to bypass it.

Knowledge check
This month's bill is ₦60,000 but the mandate's maxAmount is ₦50,000. What's correct?


Debit ₦50,000 and write off the rest

Split into two ₦30,000 debits

Create a new mandate with a higher ceiling and re-collect consent

Retry the ₦60,000 debit until it clears
Not quite — try again. Splitting to bypass the ceiling violates the customer's authorisation. Re-consent is the only compliant path.





















Module 11
4 min read
Transactions & Reconciliation
Knowledge checks · 0 / 1
0%
Reconciliation is the daily discipline of matching what your app thinks happened against what Nomba records. Skipping reconciliation is the single most common reason fintech startups lose money silently. Pull the transactions endpoint nightly, diff against your local ledger, and alert on any drift.

GET
/transactions
List transactions with filters: dateFrom, dateTo, status, type
GET
/transactions/{merchantTxRef}
Look up a single transaction by your reference
Node.js
Python
Copy
const { data } = await nomba.get("/transactions", {
  params: { dateFrom: "2026-03-01", dateTo: "2026-03-31", status: "success" },
});

for (const tx of data.transactions) {
  const local = await db.payments.findOne({ ref: tx.merchantTxRef });
  if (!local) await alertOps("Orphan transaction on Nomba", tx);
  else if (local.amount !== tx.amount) await alertOps("Amount drift", { local, tx });
}
Reconcile by reference, not by ID
Your merchantTxRef is the source of truth. Use it to join Nomba's view with yours — Nomba's internal IDs may rotate during retries.

Knowledge check
Which field anchors reconciliation between your ledger and Nomba?


Nomba's internal txId

Your merchantTxRef

The customer's email

The settlement timestamp
Not quite — try again. merchantTxRef is yours, stable, and present on both sides — internal IDs may change on retry.
← Direct Debits (Mandates)

































Mapping APIs to Tracks
Knowledge checks · 0 / 1
0%
Each hackathon track is judged on how well your integration matches a real-world Nomba use case. Use this table to identify which APIs to focus on for your track — then over-invest in the corresponding modules.

Hackathon track	Primary APIs	Bonus polish
Marketplace / multi-vendor	Sub-accounts, Transfers, Webhooks	Reconciliation dashboard
Subscription product	Checkout, Tokenized Cards, Mandates	Retry strategy, dunning emails
Treasury / payouts	Transfers, Virtual Accounts, Transactions	Idempotency, audit log
Bank-transfer checkout	Virtual Accounts, Webhooks	Real-time UI updates
BNPL / lending	Mandates, Direct Debits, Transactions	Mandate lifecycle UI
Pick depth over breadth
A judge would rather see one API used flawlessly with proper webhook handling and reconciliation than five APIs glued together.

Knowledge check
You're building BNPL — which API combination is the strongest match?


Checkout + Sub-accounts

Mandates + Direct Debits + Transactions

Virtual Accounts + Transfers

Tokenized Cards only
← Transactions & Reconciliation























Build-Week Checklist
Knowledge checks · 0 / 1
0%
Run through this list before your submission. If any item is unchecked you will lose points — these are the same checks senior engineers use during a production launch.

Security
clientSecret and webhookSecret loaded from environment variables — not in source
All webhook handlers verify the nomba-signature HMAC
Idempotency: every external write keyed on a unique merchantTxRef
Correctness
All amounts converted to kobo before sending
Recipient name verified via /transfers/bank/lookup before transfers
Webhook handler is idempotent against duplicate requestId values
Over- and under-payment branches handled for virtual accounts
Operations
Nightly reconciliation job comparing /transactions to your ledger
Structured logging on every Nomba call with merchantTxRef tagged
Health-check endpoint your judges can hit to see green status
You're certification-ready
Mark this module complete to unlock the Certified Nomba Developer assessment.

Knowledge check
Where should clientSecret and webhookSecret live in production?


Hard-coded in source so they ship with the build

Committed to a .env file in the repo

In environment variables loaded from a secret manager — never in source

In the front-end bundle behind obfuscation
← Mapping APIs to Tracks