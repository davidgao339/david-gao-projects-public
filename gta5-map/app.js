document.addEventListener('DOMContentLoaded', async () => {
    // === Map Configuration ===
    const map = L.map('map', {
        crs: L.CRS.Simple,
        minZoom: -3,
        maxZoom: 2,
        zoomControl: true,
        attributionControl: false
    });

    const MAP_STYLES = {
        atlas: 'https://www.bragitoff.com/wp-content/uploads/2015/11/GTAV_ATLUS_8192x8192.png',
        satellite: 'https://www.bragitoff.com/wp-content/uploads/2015/11/GTAV-HD-MAP-satellite.jpg',
        roadmap: 'https://www.bragitoff.com/wp-content/uploads/2015/11/GTAV-HD-MAP-roadmap.jpg'
    };

    const imageBounds = [[0, 0], [8192, 8192]];
    let currentMapLayer = L.imageOverlay(MAP_STYLES.atlas, imageBounds).addTo(map);
    map.setView([4096, 4096], -2);

    // Style switcher
    const styleSelect = document.getElementById('map-style-select');
    styleSelect.addEventListener('change', (e) => {
        const style = e.target.value;
        map.removeLayer(currentMapLayer);
        const mapContainer = document.getElementById('map-container');
        if (style === 'atlas') mapContainer.style.backgroundColor = '#0fa8d2';
        else if (style === 'satellite') mapContainer.style.backgroundColor = '#10161a';
        else mapContainer.style.backgroundColor = '#d1e6e9';
        currentMapLayer = L.imageOverlay(MAP_STYLES[style], imageBounds).addTo(map);
    });

    // === Final Locked Calibration (Curve-Corrected) ===
    const CALIBRATION = {"scaleY":0.0006097838807284631,"scaleX":0.0006107432690086729,"offsetY":-4013.8487228847807,"offsetX":12228.895602596593};

    // === FontAwesome Icon Mapping ===
    const ICON_MAP = {
        'Ammu-Nation': 'fa-crosshairs',
        'ATM': 'fa-money-bill-wave',
        'Automotive Shop': 'fa-wrench',
        'Barber': 'fa-cut',
        'Building': 'fa-building',
        'Car Wash': 'fa-tint',
        'Cinema': 'fa-film',
        'Clothing': 'fa-tshirt',
        'Fire Station': 'fa-fire-extinguisher',
        'Food & Drink': 'fa-hamburger',
        'Hospital': 'fa-hospital',
        'Lookout Point': 'fa-binoculars',
        'Mountain Peak': 'fa-mountain',
        'Police Station': 'fa-shield-alt',
        'Store': 'fa-shopping-basket',
        'Strip Club': 'fa-cocktail',
        'Tattoo': 'fa-pen',
        'Darts': 'fa-bullseye',
        'Flight School': 'fa-plane',
        'Golfing': 'fa-golf-ball',
        'Hunting': 'fa-paw',
        'Parachuting': 'fa-parachute-box',
        'Races': 'fa-flag-checkered',
        'Shooting': 'fa-crosshairs',
        'Tennis': 'fa-table-tennis',
        'Triathlon': 'fa-running',
        'Yoga': 'fa-child',
        'Mission': 'fa-star',
        'Random Event': 'fa-question',
        'Strangers & Freaks': 'fa-user-secret',
        'Epsilon Tract': 'fa-book',
        'Hidden Package': 'fa-box',
        'Knife Flight': 'fa-fighter-jet',
        'Letter Scrap': 'fa-envelope',
        'Monkey Mosaic': 'fa-camera',
        'Nuclear Waste': 'fa-radiation',
        'Peyote Plant': 'fa-leaf',
        'Property': 'fa-home',
        'Realty Sign': 'fa-sign',
        'Spaceship Part': 'fa-rocket',
        'Stunt Jump': 'fa-car-side',
        'Submarine Part': 'fa-anchor',
        'Under The Bridge': 'fa-road',
        'Body Armor': 'fa-shield-alt',
        'Health Pack': 'fa-medkit',
        'Vehicle Spawn': 'fa-car',
        'Weapon Pickup': 'fa-gun',
        'Action Figure': 'fa-robot',
        'Apartment': 'fa-building',
        'Bunker': 'fa-dungeon',
        'Clothing Scrap': 'fa-socks',
        'Clubhouse': 'fa-motorcycle',
        'Executive Office': 'fa-briefcase',
        'Exotic Export': 'fa-car',
        'Facility': 'fa-industry',
        'Gang Attack': 'fa-skull',
        'Garage': 'fa-warehouse',
        'Hangar': 'fa-plane-departure',
        'Nightclub': 'fa-music',
        'Playing Card': 'fa-layer-group',
        'Signal Jammer': 'fa-broadcast-tower',
        'Warehouse': 'fa-boxes',
        'Movie Prop': 'fa-video',
        'Slasher Clue': 'fa-search',
        'Arcade': 'fa-gamepad',
        'Agency': 'fa-user-tie',
        'Auto Shop': 'fa-wrench',
        'Easter Egg': 'fa-egg'
    };

    function getIcon(title) {
        return ICON_MAP[title] || 'fa-map-marker-alt';
    }

    // === Marker Management & Cloud Sync ===
    const CLOUD_API = "https://jsonblob.com/api/jsonBlob";
    let syncId = localStorage.getItem("gta5_sync_id") || "";
    const syncInput = document.getElementById("sync-id");
    const syncStatus = document.getElementById("sync-status");
    if (syncInput && syncId) syncInput.value = syncId;

    if (document.getElementById("btn-sync-new")) {
        document.getElementById("btn-sync-new").onclick = async () => {
            try {
                syncStatus.textContent = "Creating...";
                const resp = await fetch(CLOUD_API, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Accept": "application/json" },
                    body: JSON.stringify(Array.from(foundLocations))
                });
                const locationStr = resp.headers.get("Location");
                if (locationStr) {
                    syncId = locationStr.split("/").pop();
                    localStorage.setItem("gta5_sync_id", syncId);
                    syncInput.value = syncId;
                    syncStatus.textContent = "Created! Copy ID.";
                } else {
                    syncStatus.textContent = "Error creating.";
                }
            } catch (e) { syncStatus.textContent = "Error."; }
        };

        document.getElementById("btn-sync-pull").onclick = async () => {
            const id = syncInput.value.trim();
            if (!id) return;
            try {
                syncStatus.textContent = "Downloading...";
                const resp = await fetch(`${CLOUD_API}/${id}`, { headers: { "Accept": "application/json" } });
                if (resp.ok) {
                    const data = await resp.json();
                    foundLocations = new Set(data);
                    saveProgress();
                    for (const locId in markerInstances) {
                        const idInt = parseInt(locId);
                        const isFound = foundLocations.has(idInt);
                        const m = markerInstances[locId].marker;
                        
                        // Toggle Leaflet DOM classes manually or re-render
                        if (m._icon) {
                            if (isFound) m._icon.classList.add('found');
                            else m._icon.classList.remove('found');
                        }
                    }
                    syncId = id;
                    localStorage.setItem("gta5_sync_id", syncId);
                    syncStatus.textContent = "Synced!";
                } else { syncStatus.textContent = "Not found."; }
            } catch (e) { syncStatus.textContent = "Error."; }
        };
    }

    async function pushToCloud() {
        if (!syncId) return;
        try {
            syncStatus.textContent = "Saving to cloud...";
            await fetch(`${CLOUD_API}/${syncId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json", "Accept": "application/json" },
                body: JSON.stringify(Array.from(foundLocations))
            });
            syncStatus.textContent = "Cloud saved.";
            setTimeout(() => { if (syncStatus.textContent === "Cloud saved.") syncStatus.textContent = ""; }, 2000);
        } catch (e) { syncStatus.textContent = "Cloud save failed."; }
    }

    const STORAGE_KEY = 'gta5_found_locations_mapgenie';
    let foundLocations = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
    
    let pushTimeout = null;
    function saveProgress() {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(foundLocations)));
        updateProgressUI();
        if (syncId) {
            clearTimeout(pushTimeout);
            pushTimeout = setTimeout(pushToCloud, 1500);
        }
    }

    const markerInstances = {};
    const layerGroups = {};
    let rawLocations = [];
    let grouped = {};

    const ONLINE_CATEGORIES = new Set([
        'Action Figure', 'Apartment', 'Bunker', 'Clothing Scrap', 
        'Clubhouse', 'Executive Office', 'Exotic Export', 'Facility', 
        'Gang Attack', 'Garage', 'Hangar', 'LD Organics Product', 
        'Nightclub', 'Peyote Plant', 'Playing Card', 'Signal Jammer', 
        'Warehouse', 'Movie Prop', 'Slasher Clue', 'Arcade', 
        'Agency', 'Auto Shop'
    ]);

    try {
        const response = await fetch('locations.json');
        rawLocations = await response.json();
        
        rawLocations.forEach(loc => {
            if (!loc.category || !loc.latitude || !loc.longitude) return;
            const type = loc.category.title || 'Other';
            
            // Skip online categories
            if (ONLINE_CATEGORIES.has(type)) return;

            if (!grouped[type]) grouped[type] = {
                color: loc.category.color || '#3498db',
                locations: []
            };
            grouped[type].locations.push(loc);
        });

        // Sort categories alphabetically
        const sortedTypes = Object.keys(grouped).sort();

        const sidebarList = document.getElementById('category-list');
        sidebarList.innerHTML = ''; 

        for (const type of sortedTypes) {
            const data = grouped[type];
            layerGroups[type] = L.featureGroup().addTo(map);
            const color = data.color.startsWith('#') ? data.color : '#34495e';
            const iconClass = getIcon(type);

            const categoryDiv = document.createElement('div');
            categoryDiv.className = 'category-item';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'category-checkbox';
            checkbox.checked = true;
            checkbox.addEventListener('change', (e) => {
                if (e.target.checked) map.addLayer(layerGroups[type]);
                else map.removeLayer(layerGroups[type]);
            });

            const iconSpan = document.createElement('span');
            iconSpan.className = 'category-icon';
            iconSpan.style.color = color;
            iconSpan.innerHTML = `<i class="fas ${iconClass}"></i>`;

            const title = document.createElement('div');
            title.className = 'category-title';
            title.textContent = type;

            const progressSpan = document.createElement('span');
            progressSpan.className = 'category-progress';
            progressSpan.id = `progress-${type.replace(/[^a-zA-Z0-9]/g, '-')}`;

            categoryDiv.appendChild(checkbox);
            categoryDiv.appendChild(iconSpan);
            categoryDiv.appendChild(title);
            categoryDiv.appendChild(progressSpan);
            
            // Clicking the row toggles the checkbox
            categoryDiv.addEventListener('click', (e) => {
                if (e.target !== checkbox) {
                    checkbox.checked = !checkbox.checked;
                    checkbox.dispatchEvent(new Event('change'));
                }
            });

            sidebarList.appendChild(categoryDiv);
        }

        renderMarkers();

        // Show/Hide All Buttons
        document.getElementById('btn-show-all').addEventListener('click', () => {
            document.querySelectorAll('.category-checkbox').forEach(cb => {
                if (!cb.checked) {
                    cb.checked = true;
                    cb.dispatchEvent(new Event('change'));
                }
            });
        });

        document.getElementById('btn-hide-all').addEventListener('click', () => {
            document.querySelectorAll('.category-checkbox').forEach(cb => {
                if (cb.checked) {
                    cb.checked = false;
                    cb.dispatchEvent(new Event('change'));
                }
            });
        });

    } catch (e) {
        console.error("Error loading locations:", e);
    }

    function renderMarkers() {
        for (const [type, data] of Object.entries(grouped)) {
            const layerGroup = layerGroups[type];
            const color = data.color.startsWith('#') ? data.color : '#34495e';
            const iconClass = getIcon(type);

            data.locations.forEach(loc => {
                // Spherical Mercator un-warp
                const pt = L.Projection.SphericalMercator.project(L.latLng(loc.latitude, loc.longitude));
                const mappedY = pt.y * CALIBRATION.scaleY + CALIBRATION.offsetY;
                const mappedX = pt.x * CALIBRATION.scaleX + CALIBRATION.offsetX;

                const isFound = foundLocations.has(loc.id);
                
                // Use FontAwesome inside a circular div
                const markerHtml = `
                    <div class="custom-marker ${isFound ? 'found' : ''}" style="background-color: ${color}; width: 22px; height: 22px;">
                        <i class="fas ${iconClass}"></i>
                    </div>
                `;
                const icon = L.divIcon({ html: markerHtml, className: '', iconSize: [22, 22], iconAnchor: [11, 11] });

                const marker = L.marker([mappedY, mappedX], { icon });
                
                markerInstances[loc.id] = { marker, type, data: loc };

                const desc = loc.description ? loc.description.replace(/\\n/g, '<br>') : '';
                const popupDiv = document.createElement('div');
                popupDiv.className = 'popup-content';
                
                const renderPopupContent = () => {
                    const currentlyFound = foundLocations.has(loc.id);
                    popupDiv.innerHTML = `
                        <h3><i class="fas ${iconClass}" style="color:${color}; margin-right:5px;"></i> ${loc.title}</h3>
                        ${desc ? `<p>${desc}</p>` : ''}
                        <button class="toggle-found-btn ${currentlyFound ? 'is-found' : ''}" data-id="${loc.id}">
                            ${currentlyFound ? 'Mark as Unfound' : 'Mark as Found'}
                        </button>
                    `;
                    
                    popupDiv.querySelector('.toggle-found-btn').addEventListener('click', (e) => {
                        const id = parseInt(e.target.getAttribute('data-id'));
                        toggleFound(id);
                        renderPopupContent(); // Re-render popup content to switch button state
                    });
                };
                
                renderPopupContent();
                marker.bindPopup(popupDiv);
                layerGroup.addLayer(marker);
            });
        }
        updateProgressUI();
    }

    function toggleFound(id) {
        if (foundLocations.has(id)) foundLocations.delete(id);
        else foundLocations.add(id);
        
        saveProgress();
        
        const m = markerInstances[id];
        if (m && m.marker._icon) {
            const innerDiv = m.marker._icon.querySelector('.custom-marker');
            if (innerDiv) {
                if (foundLocations.has(id)) innerDiv.classList.add('found');
                else innerDiv.classList.remove('found');
            }
        }
    }

    function updateProgressUI() {
        const counts = {};
        const totals = {};
        for (const id in markerInstances) {
            const type = markerInstances[id].type;
            totals[type] = (totals[type] || 0) + 1;
            if (foundLocations.has(parseInt(id))) counts[type] = (counts[type] || 0) + 1;
        }
        for (const type in totals) {
            const el = document.getElementById(`progress-${type.replace(/[^a-zA-Z0-9]/g, '-')}`);
            if (el) el.textContent = `${counts[type] || 0} / ${totals[type]}`;
        }
    }
});
