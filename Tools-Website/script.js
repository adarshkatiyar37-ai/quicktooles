let search=document.getElementById("search")

search.addEventListener("keyup",function(){

let filter=search.value.toLowerCase()

let cards=document.querySelectorAll(".card")

cards.forEach(function(card){

let text=card.textContent.toLowerCase()

card.style.display=text.includes(filter)?"block":"none"

})

})