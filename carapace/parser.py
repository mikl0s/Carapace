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
        
        # Apply parsing quirks to fix wiki inconsistencies
        self._apply_parsing_quirks()
        
        # Deduplicate addons by name and repo URL while preserving tags
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
            # Skip empty list items
            if li.get('class') == 'mw-empty-elt':
                continue
                
            # Get all text and links from the list item
            text_content = ''.join(li.itertext()).strip()
            links = li.xpath('.//a[@href]')
            
            for link in links:
                href = link.get('href')
                addon_name = link.text_content().strip()
                
                # Skip special markers and non-addon links
                if self._is_special_marker(addon_name):
                    continue
                if addon_name in ['/r/pfUI', 'Releases page']:
                    continue
                    
                # Store ANY URL we find
                if href:
                    # Convert relative URLs to absolute
                    url = href
                    if href.startswith('/wiki/'):
                        url = 'https://turtle-wow.fandom.com' + href
                    elif not href.startswith('http'):
                        # Other relative URLs
                        url = 'https://turtle-wow.fandom.com' + href
                    
                    # Extract description from the parent text
                    parent_text = ''.join(li.itertext()).strip()
                    description = self._extract_description(parent_text, addon_name)
                    
                    addon = {
                        'name': addon_name,
                        'repo_url': url,  # Store ANY URL
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
        
        # Iterate through siblings after the header until we hit the SuperWoW or unsupported sections
        current = full_list_header[0].getnext() if full_list_header else None
        
        while current is not None:
            # Stop if we hit the SuperWoW sections
            if current.tag == 'p' and 'Addons that require SuperWoW' in ''.join(current.itertext()):
                break
            if current.tag == 'p' and 'Addons that gain additional features' in ''.join(current.itertext()):
                break
            # Stop if we hit the "Further Addons Collections" section (unsupported)
            if current.tag == 'h2':
                header_text = ''.join(current.itertext())
                if 'Further Addons Collections' in header_text:
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
            
            # Find ANY URL - store whatever we have
            addon_url = None
            
            # First, try to find a proper repo URL (GitHub, GitLab, etc)
            for link in links:
                href = link.get('href')
                if self._is_addon_url(href):
                    addon_url = href
                    break
            
            # If no repo URL found, store WHATEVER URL we have from the first link
            if not addon_url:
                first_href = first_link.get('href', '')
                if first_href:
                    # Convert relative wiki URLs to absolute
                    if first_href.startswith('/wiki/'):
                        addon_url = 'https://turtle-wow.fandom.com' + first_href
                    else:
                        addon_url = first_href
                
                # Still check [Fu] or other links for better URLs
                for link in links[1:]:
                    link_text = link.text_content().strip()
                    if link_text.startswith('[') and link_text.endswith(']'):
                        href = link.get('href')
                        if href and self._is_addon_url(href):
                            addon_url = href  # Override with better URL
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
        # Find "Addons that require SuperWoW" - it's in a <p> tag followed by a table
        paragraphs = tree.xpath('//p[b[contains(text(), "Addons that require SuperWoW")]]')
        if paragraphs:
            for p in paragraphs:
                table = p.getnext()
                if table is not None and table.tag == 'table':
                    self._parse_table(table, ['superwow_required'])
        
        # Find "Addons that gain additional features with SuperWoW" 
        paragraphs = tree.xpath('//p[b[contains(text(), "Addons that gain additional features with SuperWoW")]]')
        if paragraphs:
            for p in paragraphs:
                table = p.getnext()
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
                    addon_name = link[0].text_content().strip()
                    
                    # For SuperWoW features table, description might be in 3rd column
                    if 'superwow_features' in tags and len(cells) >= 3:
                        description = cells[2].text_content().strip()
                    else:
                        # Second cell contains the description
                        description = cells[1].text_content().strip()
                    
                    # Check if this addon already exists and update tags
                    existing = self._find_addon(addon_name)
                    if existing:
                        for tag in tags:
                            if tag not in existing['tags']:
                                existing['tags'].append(tag)
                    else:
                        # Store ANY URL, not just repo URLs
                        url = href
                        if not self._is_addon_url(href):
                            # Convert relative URLs to absolute
                            if href.startswith('/wiki/'):
                                url = 'https://turtle-wow.fandom.com' + href
                        
                        addon = {
                            'name': addon_name,
                            'repo_url': url if url else '',
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
        valid_hosts = ['github.com', 'gitlab.com', 'bitbucket.org', 'shagu.org', 'tempranova.github.io', 'woblight.gitlab.io']
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
    
    def _apply_parsing_quirks(self):
        """Fix known wiki inconsistencies and quirks
        
        This function handles edge cases where the wiki has duplicate or
        inconsistent entries that shouldn't be treated as separate addons.
        """
        # Known name variations that should be unified
        # Note: For AtlasLoot, we keep the space version to match other Atlas mods
        name_mappings = {
            'atlasloot turtle': 'AtlasLoot Turtle',
            'atlasloot-turtle': 'AtlasLoot Turtle',
            'atlaslootturtlewow': 'AtlasLoot Turtle',
            'pfquest turtle': 'pfQuest-turtle',
            'pfquest-turtle': 'pfQuest-turtle',
            'bigwigs turtle': 'BigWigs-Turtle',
            'bigwigs-turtle': 'BigWigs-Turtle',
            'questie turtle': 'Questie-Turtle',
            'questie-turtle': 'Questie-Turtle',
        }
        
        # Normalize addon names
        for addon in self.addons:
            name_lower = addon['name'].lower().replace(' ', '').replace('_', '-')
            if name_lower in name_mappings:
                addon['name'] = name_mappings[name_lower]
        
        # Known broken/duplicate URLs to fix
        url_fixes = {
            'https://github.com/Lexiebean/AtlasLoot': 'https://github.com/Lexiebean/AtlasLoot',
            'https://github.com/Lexiebean/atlasloot': 'https://github.com/Lexiebean/AtlasLoot',
        }
        
        for addon in self.addons:
            if addon.get('repo_url'):
                # Normalize GitHub URLs
                url = addon['repo_url'].lower()
                for bad_url, good_url in url_fixes.items():
                    if url == bad_url.lower():
                        addon['repo_url'] = good_url
                        break
    
    def _deduplicate_addons(self):
        """Deduplicate addons by name AND repo URL, merging tags and data"""
        # First pass: group by repo URL
        by_repo = {}
        no_repo = []
        
        for addon in self.addons:
            repo_url = addon.get('repo_url', '').lower().rstrip('/')
            if repo_url:
                if repo_url not in by_repo:
                    by_repo[repo_url] = []
                by_repo[repo_url].append(addon)
            else:
                no_repo.append(addon)
        
        # Merge addons with same repo URL
        merged = []
        for repo_url, addon_list in by_repo.items():
            if len(addon_list) == 1:
                merged.append(addon_list[0])
            else:
                # Merge multiple addons with same repo
                base = addon_list[0].copy()
                
                # Prefer the name with more specific formatting
                for addon in addon_list[1:]:
                    # Prefer names with dashes over spaces
                    if '-' in addon['name'] and '-' not in base['name']:
                        base['name'] = addon['name']
                    # Merge tags
                    for tag in addon.get('tags', []):
                        if tag not in base['tags']:
                            base['tags'].append(tag)
                    # Take longest description
                    if len(addon.get('description', '')) > len(base.get('description', '')):
                        base['description'] = addon['description']
                    # Merge any other useful data
                    if not base.get('homepage_url') and addon.get('homepage_url'):
                        base['homepage_url'] = addon['homepage_url']
                
                logger.info(f"Merged {len(addon_list)} entries for {base['name']} (same repo: {repo_url})")
                merged.append(base)
        
        # Second pass: deduplicate by name for addons without repo URLs
        seen_names = {addon['name'].lower(): addon for addon in merged}
        
        for addon in no_repo:
            name_lower = addon['name'].lower()
            if name_lower in seen_names:
                # Merge with existing
                existing = seen_names[name_lower]
                for tag in addon.get('tags', []):
                    if tag not in existing['tags']:
                        existing['tags'].append(tag)
                if len(addon.get('description', '')) > len(existing.get('description', '')):
                    existing['description'] = addon['description']
            else:
                seen_names[name_lower] = addon
                merged.append(addon)
        
        self.addons = merged