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
    map.setView([4096, 4096], -2); // Initial center

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

    // === Locked Calibration ===
    const CALIBRATION = {"scaleY":453.2059196437228,"scaleX":68.02948542440022,"offsetY":-30722.33757425435,"offsetX":12233.086283246665};

    // === Marker Management ===
    const STORAGE_KEY = 'gta5_found_locations_mapgenie';
    let foundLocations = new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
    
    function saveProgress() {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(foundLocations)));
        updateProgressUI();
    }

    const markerInstances = {};
    const layerGroups = {};
    let rawLocations = [];
    let grouped = {};

    try {
        const response = await fetch('locations.json');
        rawLocations = await response.json();
        
        rawLocations.forEach(loc => {
            if (!loc.category || !loc.latitude || !loc.longitude) return;
            const type = loc.category.title || 'Other';
            if (!grouped[type]) grouped[type] = {
                color: loc.category.color || '#3498db',
                locations: []
            };
            grouped[type].locations.push(loc);
        });

        const sidebarList = document.getElementById('category-list');
        sidebarList.innerHTML = ''; 

        for (const [type, data] of Object.entries(grouped)) {
            layerGroups[type] = L.featureGroup().addTo(map);
            const color = data.color.startsWith('#') ? data.color : '#34495e';

            const categoryDiv = document.createElement('div');
            categoryDiv.className = 'category';
            const categoryHeader = document.createElement('div');
            categoryHeader.className = 'category-header';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = true;
            checkbox.addEventListener('change', (e) => {
                if (e.target.checked) map.addLayer(layerGroups[type]);
                else map.removeLayer(layerGroups[type]);
            });

            const title = document.createElement('h3');
            title.textContent = type;
            title.style.color = color;
            title.style.fontSize = '14px';
            title.style.margin = '0 5px';

            const progressSpan = document.createElement('span');
            progressSpan.className = 'progress-text';
            progressSpan.id = `progress-${type.replace(/[^a-zA-Z0-9]/g, '-')}`;

            categoryHeader.appendChild(checkbox);
            categoryHeader.appendChild(title);
            categoryHeader.appendChild(progressSpan);
            categoryDiv.appendChild(categoryHeader);
            
            const locList = document.createElement('ul');
            locList.className = 'location-list';
            locList.id = `list-${type.replace(/[^a-zA-Z0-9]/g, '-')}`;
            categoryDiv.appendChild(locList);
            sidebarList.appendChild(categoryDiv);
        }

        renderMarkers();

    } catch (e) {
        console.error("Error loading locations:", e);
    }

    function renderMarkers() {
        for (const [type, data] of Object.entries(grouped)) {
            const layerGroup = layerGroups[type];
            const locList = document.getElementById(`list-${type.replace(/[^a-zA-Z0-9]/g, '-')}`);
            const color = data.color.startsWith('#') ? data.color : '#34495e';

            data.locations.forEach(loc => {
                // Apply the perfect calibration
                const mappedY = loc.latitude * CALIBRATION.scaleY + CALIBRATION.offsetY;
                const mappedX = loc.longitude * CALIBRATION.scaleX + CALIBRATION.offsetX;

                const markerHtml = `<div style="background-color: ${color}; width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid white; box-shadow: 0 0 3px rgba(0,0,0,0.5);"></div>`;
                const icon = L.divIcon({ html: markerHtml, className: 'custom-marker', iconSize: [15, 15], iconAnchor: [7.5, 7.5] });

                const marker = L.marker([mappedY, mappedX], { icon });
                
                markerInstances[loc.id] = { marker, type, data: loc };
                if (foundLocations.has(loc.id)) marker.setOpacity(0.4);

                const desc = loc.description ? loc.description.replace(/\\n/g, '<br>') : '';
                const popupDiv = document.createElement('div');
                popupDiv.className = 'popup-content';
                popupDiv.innerHTML = `
                    <h3 style="margin:0 0 5px 0;">${loc.title}</h3>
                    ${desc ? `<p style="font-size:12px; margin:0 0 10px 0;">${desc}</p>` : ''}
                    <button class="toggle-found-btn" data-id="${loc.id}" style="width:100%; padding:5px; cursor:pointer;">
                        ${foundLocations.has(loc.id) ? 'Mark as Unfound' : 'Mark as Found'}
                    </button>
                `;

                popupDiv.addEventListener('click', (e) => {
                    if (e.target.classList.contains('toggle-found-btn')) {
                        const id = parseInt(e.target.getAttribute('data-id'));
                        toggleFound(id);
                        e.target.textContent = foundLocations.has(id) ? 'Mark as Unfound' : 'Mark as Found';
                    }
                });

                marker.bindPopup(popupDiv);
                layerGroup.addLayer(marker);

                const li = document.createElement('li');
                li.id = `sidebar-loc-${loc.id}`;
                li.className = foundLocations.has(loc.id) ? 'found' : '';
                li.style.fontSize = '12px';
                li.innerHTML = `<label style="display:flex; align-items:center; cursor:pointer;"><input type="checkbox" class="sidebar-check" data-id="${loc.id}" ${foundLocations.has(loc.id) ? 'checked' : ''} style="margin-right:5px;"> ${loc.title}</label>`;
                
                li.addEventListener('click', (e) => {
                    if (e.target.type !== 'checkbox') {
                        map.setView([mappedY, mappedX], 1);
                        marker.openPopup();
                    }
                });

                const check = li.querySelector('.sidebar-check');
                check.addEventListener('change', (e) => toggleFound(loc.id, e.target.checked));

                locList.appendChild(li);
            });
        }
        updateProgressUI();
    }

    function toggleFound(id, forceState = null) {
        if (forceState === null) {
            if (foundLocations.has(id)) foundLocations.delete(id);
            else foundLocations.add(id);
        } else {
            if (forceState) foundLocations.add(id);
            else foundLocations.delete(id);
        }
        saveProgress();
        const m = markerInstances[id];
        if (m) m.marker.setOpacity(foundLocations.has(id) ? 0.4 : 1.0);
        const li = document.getElementById(`sidebar-loc-${id}`);
        if (li) {
            li.className = foundLocations.has(id) ? 'found' : '';
            const check = li.querySelector('.sidebar-check');
            if (check) check.checked = foundLocations.has(id);
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

    // === Cloud Sync Feature ===
    const CLOUD_API = "https://jsonblob.com/api/jsonBlob";
    let syncId = localStorage.getItem("gta5_sync_id") || "";
    const syncInput = document.getElementById("sync-id");
    const syncStatus = document.getElementById("sync-status");
    
    if (syncId) syncInput.value = syncId;

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
        } catch (e) {
            syncStatus.textContent = "Error.";
        }
    };

    document.getElementById("btn-sync-pull").onclick = async () => {
        const id = syncInput.value.trim();
        if (!id) return;
        try {
            syncStatus.textContent = "Downloading...";
            const resp = await fetch(`${CLOUD_API}/${id}`, {
                headers: { "Accept": "application/json" }
            });
            if (resp.ok) {
                const data = await resp.json();
                foundLocations = new Set(data);
                saveProgress();
                
                // Re-render visuals
                for (const locId in markerInstances) {
                    const idInt = parseInt(locId);
                    markerInstances[locId].marker.setOpacity(foundLocations.has(idInt) ? 0.4 : 1.0);
                    const li = document.getElementById(`sidebar-loc-${idInt}`);
                    if (li) {
                        li.className = foundLocations.has(idInt) ? "found" : "";
                        const check = li.querySelector(".sidebar-check");
                        if (check) check.checked = foundLocations.has(idInt);
                    }
                }
                
                syncId = id;
                localStorage.setItem("gta5_sync_id", syncId);
                syncStatus.textContent = "Synced!";
            } else {
                syncStatus.textContent = "Not found.";
            }
        } catch (e) {
            syncStatus.textContent = "Error.";
        }
    };

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
        } catch (e) {
            syncStatus.textContent = "Cloud save failed.";
        }
    }

    // Wrap saveProgress to trigger cloud sync
    const originalSaveProgress = saveProgress;
    let pushTimeout = null;
    saveProgress = function() {
        originalSaveProgress();
        if (syncId) {
            clearTimeout(pushTimeout);
            pushTimeout = setTimeout(pushToCloud, 1500); // Debounce
        }
    };

