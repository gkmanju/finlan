"""
Plaid API integration for financial data syncing
"""
import os
from datetime import datetime, timedelta
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest


class PlaidClient:
    def __init__(self, client_id: str, secret: str, environment: str = 'sandbox'):
        """
        Initialize Plaid client
        
        Args:
            client_id: Plaid client ID
            secret: Plaid secret key
            environment: 'sandbox' or 'production'
        """
        if environment == 'production':
            host = plaid.Environment.Production
        else:
            # Both 'sandbox' and 'development' use Sandbox environment
            host = plaid.Environment.Sandbox
        
        configuration = plaid.Configuration(
            host=host,
            api_key={
                'clientId': client_id,
                'secret': secret,
            }
        )
        
        api_client = plaid.ApiClient(configuration)
        self.client = plaid_api.PlaidApi(api_client)
    
    def create_link_token(self, user_id: str, user_email: str):
        """Create a Link token for Plaid Link initialization"""
        try:
            request = LinkTokenCreateRequest(
                products=[Products("transactions")],
                client_name="FinLAN Portfolio",
                country_codes=[CountryCode('US')],
                language='en',
                user=LinkTokenCreateRequestUser(
                    client_user_id=str(user_id)
                )
            )
            response = self.client.link_token_create(request)
            return response.to_dict()
        except plaid.ApiException as e:
            raise Exception(f"Error creating link token: {e}")
    
    def exchange_public_token(self, public_token: str):
        """Exchange public token for access token"""
        try:
            request = ItemPublicTokenExchangeRequest(
                public_token=public_token
            )
            response = self.client.item_public_token_exchange(request)
            return {
                'access_token': response['access_token'],
                'item_id': response['item_id']
            }
        except plaid.ApiException as e:
            raise Exception(f"Error exchanging token: {e}")
    
    def get_accounts(self, access_token: str):
        """Get all accounts for an access token"""
        try:
            request = AccountsGetRequest(
                access_token=access_token
            )
            response = self.client.accounts_get(request)
            return response.to_dict()
        except plaid.ApiException as e:
            raise Exception(f"Error getting accounts: {e}")
    
    def get_transactions(self, access_token: str, start_date: datetime, end_date: datetime):
        """Get transactions for date range"""
        try:
            request = TransactionsGetRequest(
                access_token=access_token,
                start_date=start_date.date(),
                end_date=end_date.date()
            )
            response = self.client.transactions_get(request)
            return response.to_dict()
        except plaid.ApiException as e:
            raise Exception(f"Error getting transactions: {e}")
    
    def get_investment_holdings(self, access_token: str):
        """Get investment holdings"""
        try:
            request = InvestmentsHoldingsGetRequest(
                access_token=access_token
            )
            response = self.client.investments_holdings_get(request)
            return response.to_dict()
        except plaid.ApiException as e:
            raise Exception(f"Error getting holdings: {e}")
    
    def get_investment_transactions(self, access_token: str, start_date: datetime, end_date: datetime):
        """Get investment transactions"""
        try:
            request = InvestmentsTransactionsGetRequest(
                access_token=access_token,
                start_date=start_date.date(),
                end_date=end_date.date()
            )
            response = self.client.investments_transactions_get(request)
            return response.to_dict()
        except plaid.ApiException as e:
            raise Exception(f"Error getting investment transactions: {e}")


def get_plaid_client():
    """Get configured Plaid client from environment variables"""
    client_id = os.getenv('PLAID_CLIENT_ID')
    secret = os.getenv('PLAID_SECRET')
    environment = os.getenv('PLAID_ENV', 'sandbox')
    
    if not client_id or not secret:
        raise Exception("Plaid credentials not configured. Set PLAID_CLIENT_ID and PLAID_SECRET environment variables.")
    
    return PlaidClient(client_id, secret, environment)
