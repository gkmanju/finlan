"""
Fidelity web scraper for automated account sync
"""
import time
import logging
from decimal import Decimal
from datetime import date, datetime
from typing import Dict, List, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

logger = logging.getLogger(__name__)


class FidelityScraper:
    """Scrape account and holdings data from Fidelity"""
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.driver = None
        
    def _init_driver(self):
        """Initialize Chrome webdriver"""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--disable-dev-tools')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--no-first-run')
        chrome_options.add_argument('--no-default-browser-check')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument(
            '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Use Google Chrome
        chrome_options.binary_location = '/usr/bin/google-chrome-stable'
        
        # Let Selenium 4 handle driver management automatically
        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    def _find_first(self, wait: WebDriverWait, locators: List[tuple]):
        """Try multiple locators and return the first element found."""
        last_error = None
        for locator in locators:
            try:
                return wait.until(EC.presence_of_element_located(locator))
            except Exception as e:
                last_error = e
        raise last_error
        
    def login(self, username: str, password: str) -> bool:
        """
        Login to Fidelity
        Returns True if successful, False otherwise
        """
        try:
            if not self.driver:
                self._init_driver()
            
            logger.info("Navigating to Fidelity login page")
            self.driver.get("https://digital.fidelity.com/prgw/digital/login/full-page")
            
            # Wait for username field
            wait = WebDriverWait(self.driver, 30)
            username_field = self._find_first(
                wait,
                [
                    (By.ID, "userId-input"),
                    (By.NAME, "username"),
                    (By.CSS_SELECTOR, "input[autocomplete='username']"),
                    (By.CSS_SELECTOR, "input[type='text'][name*='user'], input[type='text'][id*='user']"),
                ],
            )
            
            # Enter credentials
            username_field.send_keys(username)
            time.sleep(1)
            
            password_field = self._find_first(
                wait,
                [
                    (By.ID, "password"),
                    (By.NAME, "password"),
                    (By.CSS_SELECTOR, "input[type='password']"),
                ],
            )
            password_field.send_keys(password)
            time.sleep(1)
            
            # Click login button
            login_button = self._find_first(
                wait,
                [
                    (By.ID, "fs-login-button"),
                    (By.CSS_SELECTOR, "button[type='submit']"),
                    (By.CSS_SELECTOR, "input[type='submit']"),
                ],
            )
            self.driver.execute_script("arguments[0].click();", login_button)
            
            # Wait for either dashboard or MFA prompt
            time.sleep(5)
            
            # Check if we're at the dashboard (successful login)
            try:
                wait.until(EC.presence_of_element_located((By.CLASS_NAME, "acct-selector")))
                logger.info("Login successful")
                return True
            except TimeoutException:
                # Check for MFA requirement
                current_url = self.driver.current_url
                if 'mfa' in current_url.lower() or 'authenticate' in current_url.lower():
                    logger.warning("MFA required - manual intervention needed")
                    # Give user time to complete MFA
                    time.sleep(60)
                    try:
                        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "acct-selector")))
                        logger.info("Login successful after MFA")
                        return True
                    except TimeoutException:
                        logger.error("MFA timeout or failed")
                        return False
                else:
                    logger.error("Login failed - unknown state")
                    return False
                    
        except Exception as e:
            logger.error(f"Login error: {repr(e)}")
            try:
                screenshot_path = "/tmp/fidelity_login_error.png"
                self.driver.save_screenshot(screenshot_path)
                logger.error(f"Saved login screenshot to {screenshot_path}")
            except Exception:
                pass
            return False
    
    def get_accounts(self) -> List[Dict]:
        """
        Scrape account balances from Fidelity dashboard
        Returns list of account dictionaries
        """
        accounts = []
        
        try:
            if not self.driver:
                raise Exception("Driver not initialized - call login() first")
            
            # Navigate to positions page
            self.driver.get("https://digital.fidelity.com/ftgw/digital/portfolio/positions")
            time.sleep(3)
            
            wait = WebDriverWait(self.driver, 20)
            
            # Wait for account dropdown
            account_dropdown = wait.until(
                EC.presence_of_element_located((By.CLASS_NAME, "acct-selector"))
            )
            
            # Click to expand accounts
            account_dropdown.click()
            time.sleep(2)
            
            # Get all account options
            account_options = self.driver.find_elements(By.CSS_SELECTOR, ".acct-selector-option")
            
            for option in account_options:
                try:
                    account_text = option.text.strip()
                    if not account_text:
                        continue
                    
                    # Parse account info (format varies)
                    # Example: "INDIVIDUAL - TOD | ...1234 | $50,000.00"
                    parts = [p.strip() for p in account_text.split('|')]
                    
                    if len(parts) >= 3:
                        account_type = parts[0]
                        account_number = parts[1].replace('...', '')
                        balance_str = parts[2].replace('$', '').replace(',', '').strip()
                        
                        try:
                            balance = Decimal(balance_str)
                        except:
                            balance = Decimal('0')
                        
                        accounts.append({
                            'institution': 'Fidelity',
                            'account_type': account_type,
                            'account_number_last4': account_number[-4:] if len(account_number) >= 4 else account_number,
                            'balance': balance,
                            'raw_type': account_type
                        })
                        
                except Exception as e:
                    logger.error(f"Error parsing account option: {e}")
                    continue
            
            logger.info(f"Found {len(accounts)} accounts")
            return accounts
            
        except Exception as e:
            logger.error(f"Error getting accounts: {e}")
            return []
    
    def get_holdings(self, account_id: Optional[str] = None) -> List[Dict]:
        """
        Scrape holdings for a specific account or all accounts
        Returns list of holding dictionaries
        """
        holdings = []
        
        try:
            if not self.driver:
                raise Exception("Driver not initialized - call login() first")
            
            # Navigate to positions page
            self.driver.get("https://digital.fidelity.com/ftgw/digital/portfolio/positions")
            time.sleep(3)
            
            wait = WebDriverWait(self.driver, 20)
            
            # Wait for positions table
            positions_table = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".positions-table, [data-testid='positions-table']"))
            )
            
            # Get all position rows
            rows = self.driver.find_elements(By.CSS_SELECTOR, "tr[data-row-type='position']")
            
            for row in rows:
                try:
                    # Extract data from cells
                    cells = row.find_elements(By.TAG_NAME, "td")
                    
                    if len(cells) < 5:
                        continue
                    
                    symbol_elem = row.find_element(By.CSS_SELECTOR, ".symbol, [data-testid='symbol']")
                    symbol = symbol_elem.text.strip()
                    
                    name_elem = row.find_element(By.CSS_SELECTOR, ".description, [data-testid='description']")
                    name = name_elem.text.strip()
                    
                    quantity_elem = row.find_element(By.CSS_SELECTOR, ".quantity, [data-testid='quantity']")
                    quantity_str = quantity_elem.text.replace(',', '').strip()
                    
                    price_elem = row.find_element(By.CSS_SELECTOR, ".last-price, [data-testid='last-price']")
                    price_str = price_elem.text.replace('$', '').replace(',', '').strip()
                    
                    value_elem = row.find_element(By.CSS_SELECTOR, ".current-value, [data-testid='current-value']")
                    value_str = value_elem.text.replace('$', '').replace(',', '').strip()
                    
                    # Try to get cost basis
                    try:
                        cost_elem = row.find_element(By.CSS_SELECTOR, ".cost-basis, [data-testid='cost-basis']")
                        cost_str = cost_elem.text.replace('$', '').replace(',', '').strip()
                        cost_basis = Decimal(cost_str) if cost_str else None
                    except:
                        cost_basis = None
                    
                    holdings.append({
                        'symbol': symbol,
                        'name': name,
                        'quantity': Decimal(quantity_str) if quantity_str else Decimal('0'),
                        'current_price': Decimal(price_str) if price_str else None,
                        'current_value': Decimal(value_str) if value_str else None,
                        'cost_basis': cost_basis,
                        'asset_type': 'stock',
                        'snapshot_date': date.today()
                    })
                    
                except Exception as e:
                    logger.error(f"Error parsing holding row: {e}")
                    continue
            
            logger.info(f"Found {len(holdings)} holdings")
            return holdings
            
        except Exception as e:
            logger.error(f"Error getting holdings: {e}")
            return []
    
    def close(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()
            self.driver = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
