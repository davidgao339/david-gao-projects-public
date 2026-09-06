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

    // === Guided Auto-Calibration UI (MERCATOR FIXED) ===
    const MG_BEEKERS = { lat: 83.348067483208, lng: -124.013671875 };
    const MG_OSHEAS = { lat: 79.08014, lng: -106.094971 };

    let pixelBeekers = null;
    let pixelOsheas = null;
    let tempMarker = null;
    let step = 0; 

    const calibDiv = document.createElement('div');
    calibDiv.style.position = 'absolute';
    calibDiv.style.top = '10px';
    calibDiv.style.left = '50%';
    calibDiv.style.transform = 'translateX(-50%)';
    calibDiv.style.zIndex = '9999';
    calibDiv.style.background = '#e67e22';
    calibDiv.style.padding = '15px 30px';
    calibDiv.style.borderRadius = '8px';
    calibDiv.style.color = 'white';
    calibDiv.style.boxShadow = '0 4px 12px rgba(0,0,0,0.5)';
    calibDiv.style.textAlign = 'center';
    calibDiv.innerHTML = `
        <h4 style="margin: 0 0 10px 0;">Curve-Correction Calibration</h4>
        <p style="font-size: 12px; margin: 0 0 10px 0;">Applying Spherical Mercator Un-warp Formula...</p>
        <p id="calib-text" style="font-size: 16px; margin: 0 0 10px 0; font-weight: bold;">Click exactly where <strong>Beeker's Garage</strong> is located.</p>
        <div id="calib-controls" style="display: none;">
            <button id="btn-confirm" style="padding: 10px 20px; font-weight: bold; cursor: pointer; color: black; background: #2ecc71; border: none; border-radius: 4px; margin-right: 10px;">Confirm Point</button>
            <button id="btn-reclick" style="padding: 10px 20px; font-weight: bold; cursor: pointer; color: black; background: #f1c40f; border: none; border-radius: 4px;">Click Again</button>
        </div>
        <input type="text" id="calib-result" style="display:none; width: 100%; margin-top:10px; padding: 5px; color: black;" readonly>
    `;
    document.getElementById('map-container').appendChild(calibDiv);

    const btnConfirm = document.getElementById('btn-confirm');
    const btnReclick = document.getElementById('btn-reclick');
    const calibText = document.getElementById('calib-text');
    const calibControls = document.getElementById('calib-controls');

    map.on('click', (e) => {
        if (step === 0 || step === 2) {
            if (tempMarker) map.removeLayer(tempMarker);
            tempMarker = L.marker([e.latlng.lat, e.latlng.lng]).addTo(map);
            
            if (step === 0) {
                pixelBeekers = [e.latlng.lat, e.latlng.lng];
                calibText.innerHTML = "Is this exactly <strong>Beeker's Garage</strong>?";
                step = 1;
            } else if (step === 2) {
                pixelOsheas = [e.latlng.lat, e.latlng.lng];
                calibText.innerHTML = "Is this exactly <strong>O'Sheas Barbers Shop</strong>?";
                step = 3;
            }
            calibControls.style.display = 'block';
        }
    });

    btnReclick.onclick = () => {
        if (tempMarker) map.removeLayer(tempMarker);
        tempMarker = null;
        calibControls.style.display = 'none';
        
        if (step === 1) {
            step = 0;
            calibText.innerHTML = "Click exactly where <strong>Beeker's Garage</strong> is located.";
        } else if (step === 3) {
            step = 2;
            calibText.innerHTML = "Click exactly where <strong>O'Sheas Barbers Shop</strong> is located.";
        }
    };

    btnConfirm.onclick = () => {
        if (step === 1) {
            step = 2;
            calibControls.style.display = 'none';
            calibText.innerHTML = "Awesome! Now click exactly where <strong>O'Sheas Barbers Shop</strong> is located.";
            
            const icon = L.divIcon({ html: `<div style="background: #2ecc71; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white;"></div>`, className: 'custom-marker', iconSize: [18,18] });
            tempMarker.setIcon(icon);
            tempMarker.bindPopup("Beeker's Garage (Locked)").openPopup();
            tempMarker = null;

        } else if (step === 3) {
            step = 4;
            calibControls.style.display = 'none';
            calibText.innerHTML = "Perfect! Calculating Mercator map alignment...";
            calibDiv.style.background = '#2ecc71';
            
            const icon = L.divIcon({ html: `<div style="background: #2ecc71; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white;"></div>`, className: 'custom-marker', iconSize: [18,18] });
            tempMarker.setIcon(icon);
            tempMarker.bindPopup("O'Sheas (Locked)").openPopup();

            // === THE CRITICAL MERCATOR FIX ===
            // 1. Convert the MapGenie Lat/Lng to Flat Meters to "un-warp" them!
            const ptB = L.Projection.SphericalMercator.project(L.latLng(MG_BEEKERS.lat, MG_BEEKERS.lng));
            const ptO = L.Projection.SphericalMercator.project(L.latLng(MG_OSHEAS.lat, MG_OSHEAS.lng));

            // 2. Scale the Flat Meters to your Image Pixel clicks
            const scaleY = (pixelOsheas[0] - pixelBeekers[0]) / (ptO.y - ptB.y);
            const scaleX = (pixelOsheas[1] - pixelBeekers[1]) / (ptO.x - ptB.x);
            const offsetY = pixelBeekers[0] - (ptB.y * scaleY);
            const offsetX = pixelBeekers[1] - (ptB.x * scaleX);

            window.currentCalibration = { scaleY, scaleX, offsetY, offsetX };
            
            setTimeout(() => {
                renderMarkers(true);
                calibText.innerHTML = "Mercator Alignment Locked! Copy the text below:";
                document.getElementById('calib-result').style.display = 'block';
                document.getElementById('calib-result').value = JSON.stringify(window.currentCalibration);
            }, 500);
        }
    };


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

    } catch (e) {
        console.error("Error loading locations:", e);
    }

    function renderMarkers(isExact) {
        if (!isExact) return; // Only render when locked

        for (const [type, data] of Object.entries(grouped)) {
            const layerGroup = layerGroups[type];
            const locList = document.getElementById(`list-${type.replace(/[^a-zA-Z0-9]/g, '-')}`);
            const color = data.color.startsWith('#') ? data.color : '#34495e';

            data.locations.forEach(loc => {
                const c = window.currentCalibration;
                
                // === THE CRITICAL MERCATOR FIX ===
                // Un-warp MapGenie lat/lng to Flat Meters first...
                const pt = L.Projection.SphericalMercator.project(L.latLng(loc.latitude, loc.longitude));
                
                // ...THEN apply the linear scale!
                const mappedY = pt.y * c.scaleY + c.offsetY;
                const mappedX = pt.x * c.scaleX + c.offsetX;

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
