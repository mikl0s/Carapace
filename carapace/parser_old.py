import re
import requests
from lxml import html, etree
from typing import Dict, List, Set, Optional, Tuple
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class WikiParser:
    def __init__(self):
        self.wiki_url = "https://turtle-wow.fandom.com/wiki/Addons"
        self.addons: List[Dict] = []
        self.tag_map = {
            'recommended': 'recommended',
            'featured': 'featured',
            'leveling': 'leveling',
            'endgame': 'endgame',
            'superwow_required': 'superwow_required',
            'superwow_features': 'superwow_features'
        }
    
    def parse_from_file(self, filepath: Path) -> List[Dict]:
        """Parse addons from local HTML file"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return self._parse_html(content)
    
    def parse_from_url(self, url: Optional[str] = None) -> List[Dict]:
        """Parse addons from live wiki URL"""
        if url is None:
            url = self.wiki_url
        
        logger.info(f"Fetching wiki page from: {url}")
        response = requests.get(url, headers={'User-Agent': 'Carapace Addon Manager/0.1'})
        response.raise_for_status()
        return self._parse_html(response.text)
    
    def _parse_html(self, html_content: str) -> List[Dict]:
        """Main parsing logic"""
        tree = html.fromstring(html_content)
        self.addons = []
        
        # Parse recommended sections
        self._parse_recommended_sections(tree)
        
        # Parse the full addons list (alphabetical)
        self._parse_full_addons_list(tree)
        
        # Parse SuperWoW special tables
        self._parse_superwow_tables(tree)
        
        # Deduplicate addons by name while preserving tags
        self._deduplicate_addons()
        
        logger.info(f"Parsed {len(self.addons)} unique addons")
        return self.addons
    
    def _parse_recommended_sections(self, tree):
        """Parse the recommended addon sections"""
        content = tree.xpath('//div[@class="mw-parser-output"]')[0] if tree.xpath('//div[@class="mw-parser-output"]') else tree
        if content is None:
            return
        
        # Find "We recommend that all players choose one of these:" section
        # This text appears in a div with underline styling
        elements = content.xpath('.//div[contains(., "We recommend that all players choose")]')
        if elements:
            # Find the next ul element
            for elem in elements:
                next_ul = elem.getnext()
                if next_ul is not None and next_ul.tag == 'ul':
                    self._parse_recommended_list(next_ul, ['recommended', 'featured'])
        
        # Find "Recommended Leveling Addons:" section
        elements = content.xpath('.//div[contains(., "Recommended Leveling Addons")]')
        if elements:
            for elem in elements:
                next_ul = elem.getnext()
                if next_ul is not None and next_ul.tag == 'ul':
                    self._parse_recommended_list(next_ul, ['recommended', 'leveling'])
        
        # Find "Recommended Endgame Addons:" section  
        elements = content.xpath('.//div[contains(., "Recommended Endgame Addons")]')
        if elements:
            for elem in elements:
                next_ul = elem.getnext()
                if next_ul is not None and next_ul.tag == 'ul':
                    self._parse_recommended_list(next_ul, ['recommended', 'endgame'])
    
    def _parse_recommended_list(self, element, tags: List[str]):
        """Parse a recommended addon list (ul element)"""
        if element is None or element.tag != 'ul':
            return
        
        for li in element.xpath('.//li'):
            # Get all text and links from the list item
            text_content = ''.join(li.itertext()).strip()
            links = li.xpath('.//a[@href]')
            
            for link in links:
                href = link.get('href')
                if self._is_addon_url(href):
                    addon_name = link.text_content().strip()
                    # Skip special markers like [Fu], [Img1], [vid1], etc.
                    if self._is_special_marker(addon_name):
                        continue
                    
                    # Extract description from the parent text
                    parent_text = ''.join(li.itertext()).strip()
                    description = self._extract_description(parent_text, addon_name)
                    
                    addon = {
                        'name': addon_name,
                        'repo_url': href,
                        'description': description,
                        'tags': tags.copy()
                    }
                    self.addons.append(addon)
    
    def _parse_full_addons_list(self, tree):
        """Parse the main alphabetical addons list"""
        # Find the "Full Addons List" section
        full_list_header = tree.xpath('//h3[span[@id="Full_Addons_List"]]')
        if not full_list_header:
            return
        
        # Iterate through siblings after the header until we hit the SuperWoW sections
        current = full_list_header[0].getnext() if full_list_header else None
        
        while current is not None:
            # Stop if we hit the SuperWoW sections
            if current.tag == 'p' and 'Addons that require SuperWoW' in ''.join(current.itertext()):
                break
            if current.tag == 'p' and 'Addons that gain additional features' in ''.join(current.itertext()):
                break
            
            # Parse alphabetical sections (A, B, C, etc.)
            if current.tag == 'h3':
                # This is a letter header, get the next ul element
                next_elem = current.getnext()
                if next_elem is not None and next_elem.tag == 'ul':
                    self._parse_addon_list(next_elem)
            elif current.tag == 'ul':
                # Direct list under Full Addons List
                self._parse_addon_list(current)
            
            current = current.getnext()
    
    def _parse_addon_list(self, ul_element):
        """Parse a ul element containing addon links"""
        for li in ul_element.xpath('.//li'):
            text_content = ''.join(li.itertext()).strip()
            links = li.xpath('.//a[@href]')
            
            if not links:
                continue
                
            # Get the first link (should be the addon name)
            first_link = links[0]
            addon_name = first_link.text_content().strip()
            
            # Skip if it's a special marker
            if self._is_special_marker(addon_name):
                continue
            
            # Find the addon URL - could be the first link or a later one
            addon_url = None
            for link in links:
                href = link.get('href')
                if self._is_addon_url(href):
                    addon_url = href
                    break
            
            # If no valid URL found but we have a wiki link, extract the name
            if not addon_url and first_link.get('href', '').startswith('/wiki/'):
                # This is a wiki-only addon, we'll still track it but without a repo URL
                # Look for a [Fu] or other link that might have the actual repo
                for link in links[1:]:
                    link_text = link.text_content().strip()
                    if link_text.startswith('[') and link_text.endswith(']'):
                        # This might be a [Fu] link with the actual repo
                        href = link.get('href')
                        if self._is_addon_url(href):
                            addon_url = href
                            break
            
            # Extract description and tags from the full text
            description, extracted_tags = self._parse_addon_text(text_content, addon_name)
            
            addon = {
                'name': addon_name,
                'repo_url': addon_url if addon_url else '',
                'description': description,
                'tags': extracted_tags
            }
            self.addons.append(addon)
    
    def _parse_superwow_tables(self, tree):
        """Parse the SuperWoW requirement tables"""
        # Find "Addons that require SuperWoW" table
        headers = tree.xpath('//p[contains(text(), "Addons that require SuperWoW")]')
        if headers:
            table = headers[0].getnext()
            if table is not None and table.tag == 'table':
                self._parse_table(table, ['superwow_required'])
        
        # Find "Addons that gain additional features with SuperWoW" table
        headers = tree.xpath('//p[contains(text(), "Addons that gain additional features with SuperWoW")]')
        if headers:
            table = headers[0].getnext()
            if table is not None and table.tag == 'table':
                self._parse_table(table, ['superwow_features'])
    
    def _parse_table(self, table_element, tags: List[str]):
        """Parse a table of addons"""
        for row in table_element.xpath('.//tr'):
            cells = row.xpath('.//td')
            if len(cells) >= 2:
                # First cell contains the addon link
                link = cells[0].xpath('.//a[@href]')
                if link:
                    href = link[0].get('href')
                    if self._is_addon_url(href):
                        addon_name = link[0].text_content().strip()
                        # Second cell contains the description
                        description = cells[1].text_content().strip() if len(cells) > 1 else ""
                        
                        # Check if this addon already exists and update tags
                        existing = self._find_addon(addon_name)
                        if existing:
                            existing['tags'].extend(tags)
                        else:
                            addon = {
                                'name': addon_name,
                                'repo_url': href,
                                'description': description,
                                'tags': tags.copy()
                            }
                            self.addons.append(addon)
    
    def _parse_addon_text(self, full_text: str, addon_name: str) -> Tuple[str, List[str]]:
        """Extract description and tags from addon text"""
        tags = []
        
        # Check for special indicators in brackets
        if '[SuperWoW]' in full_text or '[SuperWOW]' in full_text:
            tags.append('superwow_features')
        
        # Extract description (text after the dash or colon)
        description = self._extract_description(full_text, addon_name)
        
        # Remove special markers from description
        description = re.sub(r'\s*\[[^\]]+\]', '', description)
        description = description.strip()
        
        return description, tags
    
    def _extract_description(self, full_text: str, addon_name: str) -> str:
        """Extract description from full text"""
        # Try to find description after dash or colon
        patterns = [
            rf'{re.escape(addon_name)}\s*[-–—]\s*(.+)',
            rf'{re.escape(addon_name)}\s*:\s*(.+)',
            rf'{re.escape(addon_name)}\s+(.+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                description = match.group(1).strip()
                # Remove trailing special markers
                description = re.sub(r'\s*\[[^\]]+\]$', '', description)
                return description
        
        # If no pattern matches, return cleaned text
        cleaned = full_text.replace(addon_name, '', 1).strip()
        cleaned = re.sub(r'\s*\[[^\]]+\]', '', cleaned)
        return cleaned.strip(' -:')
    
    def _is_addon_url(self, url: str) -> bool:
        """Check if URL is a valid addon repository URL"""
        if not url:
            return False
        # Include github, gitlab, bitbucket, and other git services
        valid_hosts = ['github.com', 'gitlab.com', 'bitbucket.org', 'shagu.org', 'tempranova.github.io']
        return any(host in url.lower() for host in valid_hosts)
    
    def _is_special_marker(self, text: str) -> bool:
        """Check if text is a special marker like [Fu], [Img1], etc."""
        markers = [r'^\[?(?:Fu|Img\d+|vid\d+|Vid\d+|Alt\d+|Screenshots?)\]?$']
        for marker in markers:
            if re.match(marker, text, re.IGNORECASE):
                return True
        return False
    
    def _find_addon(self, name: str) -> Optional[Dict]:
        """Find an addon by name in the current list"""
        for addon in self.addons:
            if addon['name'].lower() == name.lower():
                return addon
        return None
    
    def _deduplicate_addons(self):
        """Deduplicate addons by name, merging tags"""
        seen = {}
        for addon in self.addons:
            name_lower = addon['name'].lower()
            if name_lower in seen:
                # Merge tags
                existing = seen[name_lower]
                for tag in addon['tags']:
                    if tag not in existing['tags']:
                        existing['tags'].append(tag)
                # Update description if the new one is longer/better
                if len(addon.get('description', '')) > len(existing.get('description', '')):
                    existing['description'] = addon['description']
                # Update repo_url if not present
                if not existing.get('repo_url') and addon.get('repo_url'):
                    existing['repo_url'] = addon['repo_url']
            else:
                seen[name_lower] = addon
        
        self.addons = list(seen.values())