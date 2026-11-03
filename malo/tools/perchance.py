"""
Perchance AI Furry Generator integration tool for MalO.
This module provides access to the web-based furry image generator at 
https://www.perchance.org/ai-furry-generator.
"""

import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import base64

class PerchanceGenerator:
    """Interface to the Perchance AI Furry Generator web service."""
    
    def __init__(self, headless=False):
        self.driver = None
        self.headless = headless
        self.setup_driver()
        
    def setup_driver(self):
        """Initialize the Chrome WebDriver with appropriate options."""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize WebDriver: {e}")
            
    def generate_avatar(self, prompt, output_dir=None):
        """
        Generate a furry avatar using the Perchance AI Furry Generator.
        
        Args:
            prompt (str): Description of the desired furry character
            output_dir (str): Directory to save generated images
            
        Returns:
            str: Path to saved image file
        """
        if not self.driver:
            raise RuntimeError("WebDriver not initialized")
            
        try:
            # Navigate to the generator page
            self.driver.get("https://www.perchance.org/ai-furry-generator")
            
            # Wait for the prompt input field to be present
            wait = WebDriverWait(self.driver, 10)
            prompt_input = wait.until(
                EC.presence_of_element_located((By.XPATH, "//textarea[@placeholder='Enter your prompt here...']"))
            )
            
            # Clear and fill in the prompt
            prompt_input.clear()
            prompt_input.send_keys(prompt)
            
            # Find and click the generate button (it might be a button or div)
            generate_btn = None
            try:
                # Try different selectors for the generate button
                generate_selectors = [
                    "//button[contains(text(), 'Generate')]",
                    "//div[contains(@class, 'generate-btn') or contains(@class, 'btn') and text()='Generate']",
                    "//button[@type='submit']"
                ]
                
                for selector in generate_selectors:
                    try:
                        generate_btn = self.driver.find_element(By.XPATH, selector)
                        if generate_btn.is_displayed():
                            break
                    except NoSuchElementException:
                        continue
                        
                if not generate_btn:
                    # If no explicit button found, look for any clickable element near the input
                    elements = self.driver.find_elements(By.TAG_NAME, "button")
                    for el in elements:
                        if el.is_displayed() and ("generate" in el.text.lower() or 
                                                "create" in el.text.lower()):
                            generate_btn = el
                            break
                    
            except NoSuchElementException:
                # If we can't find the button, try to get any submit-like element
                pass
                
            # Wait for any loading to finish before clicking
            time.sleep(2)
            
            if not generate_btn:
                # If no specific button found, click on the page area or use a default approach
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                try:
                    prompt_input.click()
                except:
                    pass
                    
                # Try to find image output and wait for it
                time.sleep(3)
                
            else:
                generate_btn.click()
            
            # Wait for the result to appear (adjust timing as needed)
            time.sleep(5)
            
            # Find the generated image
            try:
                # Look for an img tag with a src that has 'data:image' in it or other image elements
                images = self.driver.find_elements(By.TAG_NAME, "img")
                
                result_img = None
                for img in images:
                    if img.is_displayed():
                        src = img.get_attribute("src") or ""
                        # Check if this looks like a generated image (has data:image prefix)
                        if src.startswith("data:image"):
                            result_img = img
                            break
                
                if not result_img:
                    # If we didn't find an inline data:image, try to get the first displayed image
                    for img in images[:10]:  # Limit search to first 10 images
                        if img.is_displayed():
                            src = img.get_attribute("src") or ""
                            if "perchance" in src.lower() or src:
                                result_img = img
                                break
                
                if not result_img:
                    # Try getting any image with a download or save capability
                    try:
                        # Look for download buttons/links (often these are at the bottom)
                        download_buttons = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'download') or contains(text(), 'Download')]")
                        
                        if download_buttons:
                            download_buttons[0].click()
                            
                            # Wait a bit more for downloads
                            time.sleep(3)
                            
                            # Check for downloaded file in the default Downloads directory (this won't work reliably here)
                            pass
                        
                    except Exception as e:
                        print(f"Could not click download button: {e}")
                        
                else:
                    # If we found an image with data URL, save it directly
                    src = result_img.get_attribute("src")
                    if src and src.startswith("data:image"):
                        return self.save_base64_image(src, output_dir)
                    else:
                        # For regular URLs, attempt to get the full image source via page inspection
                        pass
                        
            except Exception as e:
                print(f"Error finding or saving image: {e}")
                
        except TimeoutException:
            raise RuntimeError("Timeout waiting for elements on the page")
        except Exception as e:
            raise RuntimeError(f"Failed to generate avatar: {e}")
            
        # Try alternative approach - check if there's a download link after generation
        try:
            download_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, '.jpg') or contains(@href, '.png')]")
            if download_links:
                for link in download_links:
                    href = link.get_attribute("href")
                    # If it looks like an image URL from the site
                    if href and ("perchance" in href or "data:" in href) and (href.endswith('.jpg') or href.endswith('.png')):
                        # Try to save this URL, but since we're in headless mode we might not be able to do it directly
                        pass
        except Exception as e:
            print(f"Alternative approach failed: {e}")
            
        return None
    
    def save_base64_image(self, base64_data, output_dir=None):
        """Save a base64 encoded image to disk."""
        if not base64_data.startswith('data:image'):
            raise ValueError("Invalid base64 image data")
            
        # Extract the actual base64 content
        header, encoded = base64_data.split(",", 1)
        
        # Decode base64
        image_data = base64.b64decode(encoded)
        
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        else:
            output_dir = "generated_avatars"
            os.makedirs(output_dir, exist_ok=True)
            
        # Create a filename based on timestamp
        import uuid
        filename = f"avatar_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, "wb") as fh:
            fh.write(image_data)
            
        return filepath

    def close(self):
        """Close the WebDriver."""
        if self.driver:
            self.driver.quit()
            
    def __del__(self):
        """Cleanup on destruction."""
        self.close()

# Example usage function
def generate_persona_avatar(persona_name, description, output_dir=None):
    """
    Generate an avatar for a specific persona using Perchance.
    
    Args:
        persona_name (str): Name of the persona to generate avatar for
        description (str): Detailed description of desired furry character
        output_dir (str): Directory for saving images
        
    Returns:
        str: Path to generated image file or None if failed
    """
    generator = PerchanceGenerator()
    try:
        return generator.generate_avatar(description, output_dir)
    except Exception as e:
        print(f"Failed to generate avatar for {persona_name}: {e}")
        return None
    finally:
        generator.close()
